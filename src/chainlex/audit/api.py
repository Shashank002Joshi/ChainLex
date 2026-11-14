"""Audit and officer-governance APIs. No request may supply an agent identity."""

from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response

from chainlex.audit.agents import AGENT_DESCRIPTIONS
from chainlex.audit.memory import GovernedMemoryAgent, memory_filter
from chainlex.audit.models import (
    ActionDenied,
    AgentControl,
    AgentId,
    AuditConflict,
    AuditNotFound,
    AuditState,
    CreateAudit,
    EmbeddingUnavailable,
    GateDecision,
    MemoryCorrection,
    MemoryCreate,
    MemoryInvalidation,
    PolicyChange,
    PolicyChangeDecision,
    RetryAudit,
    WorkflowPaused,
    digest,
    utcnow,
)
from chainlex.audit.reports import ReportStore
from chainlex.audit.repository import AuditRepository, verify_ledger
from chainlex.audit.scenarios import SCENARIOS
from chainlex.auth import Principal, current_principal, require_officer
from chainlex.db.connection import get_database
from chainlex.domain.models import ControlRequest
from chainlex.services.embeddings import VoyageEmbeddings

router = APIRouter()


def get_repository(request: Request):
    return AuditRepository(get_database(request), request.app.state.settings.lease_seconds)


async def get_memory(request: Request, repo=Depends(get_repository)):
    settings = request.app.state.settings
    async with httpx.AsyncClient(timeout=30) as http:
        key = settings.voyage_api_key.get_secret_value()
        voyage = VoyageEmbeddings(http, key, settings.embedding_endpoint) if key else None
        yield GovernedMemoryAgent(repo, voyage)


def actor(principal):
    return f"{principal.tenant_id}:{principal.role}"


async def scoped_run(repo, principal, audit_id):
    run = await repo.get(principal.tenant_id, audit_id)
    if run.clearance_level > (2 if principal.role == "officer" else 1):
        raise AuditNotFound("Audit not found")
    return run


def public_run(run):
    return jsonable_encoder(
        {**run.model_dump(exclude={"checkpoint": {"query_vector", "publication"}}), "leg": run.leg}
    )


@router.get("/api/agents", tags=["audit agents"])
async def agents(principal: Principal = Depends(current_principal), repo=Depends(get_repository)):
    identities = [
        d
        async for d in repo.db.agent_identities.find({"tenant_id": principal.tenant_id}, {"_id": 0})
    ]
    return {
        "mode": "scripted_demo",
        "agents": [{"agent_id": a, **d} for a, d in AGENT_DESCRIPTIONS.items()],
        "identities": identities,
    }


@router.get("/api/audits/scenarios", tags=["audits"])
def scenarios(principal: Principal = Depends(current_principal)):
    return {"mode": "scripted_demo", "scenarios": SCENARIOS}


@router.get("/api/audits/definition", tags=["audits"])
def definition(principal: Principal = Depends(current_principal)):
    return {
        "runtime_implemented": True,
        "mode": "scripted_demo",
        "settlement_dispatch": False,
        "legs": {
            "intake": {"states": ["RECEIVED"], "checkpoint": "validated context and adapter"},
            "evidence": {
                "states": ["RETRIEVING_EVIDENCE"],
                "checkpoint": "embedding and evidence versions",
            },
            "analysis": {
                "states": ["ASSESSING_ROUTES"],
                "checkpoint": "findings, routes and memory comparison",
            },
            "draft": {
                "states": ["PUBLISHING_DRAFT"],
                "checkpoint": "saved operation and verified PDF",
            },
            "human_review": {
                "states": ["AWAITING_HUMAN_REVIEW"],
                "checkpoint": "officer gate decisions",
            },
            "finalization": {
                "states": ["PUBLISHING_FINAL", "FINALIZED"],
                "checkpoint": "verified final report",
            },
        },
        "wait_states": ["RETRY_WAIT", "MANUAL_REVIEW"],
    }


@router.post("/api/agents/{agent_id}/control", tags=["governance"])
async def agent_control(
    agent_id: AgentId,
    body: AgentControl,
    principal: Principal = Depends(require_officer),
    repo=Depends(get_repository),
):
    async def update(session, control):
        result = await repo.db.agent_identities.update_one(
            {"tenant_id": principal.tenant_id, "agent_id": agent_id},
            {
                "$set": {
                    "is_active": body.is_active,
                    "controlled_by": actor(principal),
                    "control_reason": body.reason,
                }
            },
            session=session,
        )
        if result.matched_count != 1:
            raise AuditNotFound("Agent not found")

    await repo.governance(
        principal.tenant_id,
        actor(principal),
        "AGENT_AUTHORITY_CHANGED",
        {"agent_id": agent_id, **body.model_dump()},
        update,
    )
    return {"agent_id": agent_id, "is_active": body.is_active}


@router.post("/api/audits", status_code=202, tags=["audits"])
async def create_audit(
    body: CreateAudit,
    principal: Principal = Depends(current_principal),
    repo=Depends(get_repository),
):
    run = await repo.create(
        principal.tenant_id, actor(principal), 2 if principal.role == "officer" else 1, body
    )
    return public_run(await scoped_run(repo, principal, run.audit_id))


@router.get("/api/audits/{audit_id}", tags=["audits"])
async def get_audit(
    audit_id: str, principal: Principal = Depends(current_principal), repo=Depends(get_repository)
):
    return public_run(await scoped_run(repo, principal, audit_id))


@router.get("/api/audits/{audit_id}/events", tags=["audits"])
async def events(
    audit_id: str,
    after_seq: int = Query(default=0, ge=0),
    principal: Principal = Depends(current_principal),
    repo=Depends(get_repository),
):
    await scoped_run(repo, principal, audit_id)
    return await repo.events(principal.tenant_id, audit_id, after_seq)


@router.post("/api/audits/{audit_id}/gates/{gate_id}/decision", tags=["human gates"])
async def decide_gate(
    audit_id: str,
    gate_id: str,
    body: GateDecision,
    principal: Principal = Depends(require_officer),
    repo=Depends(get_repository),
    memory=Depends(get_memory),
):
    run = await repo.get(principal.tenant_id, audit_id)
    if (
        run.state != AuditState.REVIEW
        or run.revision != body.expected_revision
        or run.analysis_digest != body.analysis_digest
    ):
        raise AuditConflict("Decision does not match the current review snapshot")
    target = next((g for g in run.gates if g.gate_id == gate_id), None)
    if target is None:
        raise AuditNotFound("Human gate not found")
    if target.status != "PENDING":
        raise AuditConflict("Gate already has a recorded decision")
    if gate_id == "final-signoff" and any(
        g.status == "PENDING" for g in run.gates if g.gate_id != gate_id
    ):
        raise AuditConflict("Resolve preceding gates before final sign-off")
    replacement = target.model_copy(
        update={
            "status": "APPROVED" if body.decision == "APPROVE" else "REJECTED",
            "decision_reason": body.reason,
            "actor_id": actor(principal),
            "decided_at": utcnow(),
        }
    )
    gates = tuple(replacement if g.gate_id == gate_id else g for g in run.gates)

    async def validate(session):
        await memory.revalidate(
            run.tenant_id, run.clearance_level, run.checkpoint["evidence"], session=session
        )

    result = await repo.commit(
        run,
        "HUMAN_GATE_DECIDED",
        actor=actor(principal),
        fenced=False,
        expected_control=run.governance_revision,
        extra=validate,
        payload={"gate_id": gate_id, **body.model_dump()},
        changes={
            "gates": gates,
            "state": AuditState.FINAL if gate_id == "final-signoff" else AuditState.REVIEW,
        },
    )
    return public_run(result)


@router.post("/api/audits/{audit_id}/retry", tags=["audits"])
async def retry(
    audit_id: str,
    body: RetryAudit,
    principal: Principal = Depends(require_officer),
    repo=Depends(get_repository),
):
    run = await repo.get(principal.tenant_id, audit_id)
    if (
        run.revision != body.expected_revision
        or run.state != AuditState.MANUAL
        or not run.resume_state
    ):
        raise AuditConflict("Only the current manual-review checkpoint can be retried")
    if run.error_code == "SOURCE_SCHEMA_NOT_SUPPORTED":
        raise AuditConflict(
            "Unsupported schemas require a new corrected audit; approval cannot install an adapter"
        )
    return public_run(
        await repo.commit(
            run,
            "RETRY_REQUESTED",
            actor=actor(principal),
            fenced=False,
            changes={
                "state": run.resume_state,
                "attempts": 0,
                "error_code": None,
                "next_attempt_at": None,
                "resume_state": None,
            },
            payload={"reason": body.reason},
        )
    )


@router.get("/api/audits/{audit_id}/reports", tags=["audit reports"])
async def reports(
    audit_id: str, principal: Principal = Depends(current_principal), repo=Depends(get_repository)
):
    await scoped_run(repo, principal, audit_id)
    return await ReportStore(repo.db).list(principal.tenant_id, audit_id)


@router.get("/api/audits/{audit_id}/reports/{version}.pdf", tags=["audit reports"])
async def download(
    audit_id: str,
    version: int,
    principal: Principal = Depends(current_principal),
    repo=Depends(get_repository),
):
    await scoped_run(repo, principal, audit_id)
    payload = await ReportStore(repo.db).download(principal.tenant_id, audit_id, version)
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="chainlex-audit-v{version}.pdf"',
        },
    )


@router.get("/api/audits/{audit_id}/export", tags=["audits"])
async def export(
    audit_id: str, principal: Principal = Depends(current_principal), repo=Depends(get_repository)
):
    run = await scoped_run(repo, principal, audit_id)
    history = await repo.events(principal.tenant_id, audit_id)
    return {
        "audit": public_run(run),
        "events": history,
        "audit_chain_valid": verify_ledger(
            history, expected_last_hash=run.last_event_hash, expected_sequence=run.revision
        ),
        "reports": await ReportStore(repo.db).list(principal.tenant_id, audit_id),
        "artifacts": [
            a
            async for a in repo.db.audit_artifacts.find(
                {"tenant_id": principal.tenant_id, "audit_id": audit_id}, {"_id": 0}
            ).sort("revision", 1)
        ],
    }


@router.post("/api/control", tags=["governance"])
async def control(
    body: ControlRequest,
    principal: Principal = Depends(require_officer),
    repo=Depends(get_repository),
):
    async def update(session, current):
        return {"paused": body.paused}

    result = await repo.governance(
        principal.tenant_id, actor(principal), "TENANT_PAUSE_CHANGED", body.model_dump(), update
    )
    return {"paused": result["paused"], "revision": result["revision"]}


@router.get("/api/memories", tags=["governed memory"])
async def memories(principal: Principal = Depends(current_principal), repo=Depends(get_repository)):
    query = (
        {"tenant_id": principal.tenant_id, "scope": "scripted_demo"}
        if principal.role == "officer"
        else memory_filter(principal.tenant_id, 1)
    )
    return [
        m
        async for m in repo.db.audit_memories.find(
            query,
            {"_id": 0, "case_embedding": 0},
        ).sort([("memory_id", 1), ("version", -1)])
    ]


@router.post("/api/memories", status_code=201, tags=["governed memory"])
async def create_memory(
    body: MemoryCreate, principal: Principal = Depends(require_officer), memory=Depends(get_memory)
):
    return await memory.create(principal.tenant_id, actor(principal), body)


@router.post("/api/memories/{memory_id}/correct", tags=["governed memory"])
async def correct_memory(
    memory_id: str,
    body: MemoryCorrection,
    principal: Principal = Depends(require_officer),
    memory=Depends(get_memory),
):
    return await memory.correct(principal.tenant_id, actor(principal), memory_id, body)


@router.post("/api/memories/{memory_id}/invalidate", tags=["governed memory"])
async def invalidate_memory(
    memory_id: str,
    body: MemoryInvalidation,
    principal: Principal = Depends(require_officer),
    memory=Depends(get_memory),
):
    return await memory.invalidate(principal.tenant_id, actor(principal), memory_id, body)


@router.get("/api/agent-policies/proposals", tags=["governance"])
async def policy_proposals(
    principal: Principal = Depends(current_principal), repo=Depends(get_repository)
):
    return [
        p
        async for p in repo.db.audit_policy_proposals.find(
            {"tenant_id": principal.tenant_id}, {"_id": 0}
        )
    ]


@router.post("/api/agent-policies/proposals", status_code=201, tags=["governance"])
async def propose_policy(
    body: PolicyChange,
    principal: Principal = Depends(current_principal),
    repo=Depends(get_repository),
):
    await repo.ensure_tenant(principal.tenant_id)
    proposal = {
        "proposal_id": "policy-" + uuid4().hex,
        "tenant_id": principal.tenant_id,
        "schema_version": 1,
        "status": "PENDING",
        "proposed_by": actor(principal),
        **body.model_dump(mode="json"),
    }
    proposal["proposal_digest"] = digest(proposal)

    async def save(session, current):
        if current["policy_version"] != body.expected_version:
            raise AuditConflict("Policy version changed")
        await repo.db.audit_policy_proposals.insert_one(dict(proposal), session=session)

    await repo.governance(
        principal.tenant_id,
        actor(principal),
        "POLICY_CHANGE_PROPOSED",
        {"proposal_id": proposal["proposal_id"], "proposal_digest": proposal["proposal_digest"]},
        save,
        bump=False,
    )
    return proposal


@router.post("/api/agent-policies/proposals/{proposal_id}/decision", tags=["governance"])
async def decide_policy(
    proposal_id: str,
    body: PolicyChangeDecision,
    principal: Principal = Depends(require_officer),
    repo=Depends(get_repository),
):
    tenant = principal.tenant_id

    async def apply(session, control):
        proposal = await repo.db.audit_policy_proposals.find_one(
            {"tenant_id": tenant, "proposal_id": proposal_id}, session=session
        )
        if proposal is None:
            raise AuditNotFound("Policy proposal not found")
        if (
            proposal["status"] != "PENDING"
            or proposal["expected_version"] != body.expected_version
            or control["policy_version"] != body.expected_version
        ):
            raise AuditConflict("Policy proposal or base version changed")
        await repo.db.audit_policy_proposals.update_one(
            {"tenant_id": tenant, "proposal_id": proposal_id, "status": "PENDING"},
            {
                "$set": {
                    "status": "APPROVED" if body.decision == "APPROVE" else "REJECTED",
                    "decided_by": actor(principal),
                    "decided_at": utcnow(),
                    "decision_reason": body.reason,
                }
            },
            session=session,
        )
        if body.decision == "REJECT":
            return {}
        policy = await repo.policy(tenant, session=session)
        version = control["policy_version"] + 1
        await repo.db.policies.insert_one(
            {
                **{k: v for k, v in policy.items() if k != "_id"},
                "_id": f"{tenant}:audit-agents:v{version}",
                "version": version,
                "blocked_route_ids": proposal["blocked_route_ids"],
                "approved_by": actor(principal),
                "proposal_digest": proposal["proposal_digest"],
            },
            session=session,
        )
        return {"policy_version": version}

    result = await repo.governance(
        tenant,
        actor(principal),
        "POLICY_CHANGE_DECIDED",
        {"proposal_id": proposal_id, **body.model_dump()},
        apply,
        bump=body.decision == "APPROVE",
    )
    return {"policy_version": result["policy_version"], "revision": result["revision"]}


def install_exception_handlers(app):
    from fastapi.responses import JSONResponse
    from pymongo.errors import PyMongoError

    for exception, status, code in (
        (AuditNotFound, 404, "AUDIT_RESOURCE_NOT_FOUND"),
        (AuditConflict, 409, "AUDIT_REVISION_CONFLICT"),
        (ActionDenied, 403, "AGENT_ACTION_DENIED"),
        (WorkflowPaused, 409, "TENANT_PAUSED"),
        (EmbeddingUnavailable, 503, "EMBEDDINGS_UNAVAILABLE"),
    ):

        async def handler(request, exc, status=status, code=code):
            return JSONResponse(
                status_code=status, content={"detail": {"code": code, "message": str(exc)}}
            )

        app.add_exception_handler(exception, handler)

    async def provider_error(request, exc):
        return JSONResponse(
            status_code=503, content={"detail": {"code": "AUDIT_DEPENDENCY_UNAVAILABLE"}}
        )

    app.add_exception_handler(PyMongoError, provider_error)
    app.add_exception_handler(httpx.HTTPError, provider_error)
