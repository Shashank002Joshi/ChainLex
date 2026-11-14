"""Transactional tests use a disposable replica-set database, never the app namespace."""

import asyncio
import os
from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from pymongo import AsyncMongoClient
from pypdf import PdfReader

from chainlex.api.app import create_app
from chainlex.audit.api import get_memory, get_repository
from chainlex.audit.engine import DurableCompletionAgent
from chainlex.audit.memory import GovernedMemoryAgent, memory_filter
from chainlex.audit.models import (
    AuditConflict,
    AuditState,
    CreateAudit,
    MemoryCorrection,
    digest,
    utcnow,
)
from chainlex.audit.reports import ReportStore
from chainlex.audit.repository import AuditRepository, verify_ledger
from chainlex.auth import Principal, current_principal
from chainlex.config import Settings
from chainlex.db.indexes import bootstrap

pytestmark = pytest.mark.integration
ANALYST = {"Authorization": "Bearer analyst-test-token"}
OFFICER = {"Authorization": "Bearer officer-test-token"}


class TestEmbeddings:
    __test__ = False

    def __init__(self):
        self.calls = []

    async def embed(self, texts, input_type):
        self.calls.append((texts, input_type))
        return [[0.01] * 1024 for _ in texts]


@pytest.fixture
async def runtime():
    uri = os.environ.get("CHAINLEX_TEST_MONGODB_URI")
    if not uri:
        pytest.skip("Set CHAINLEX_TEST_MONGODB_URI for disposable Atlas/replica-set tests")
    mongo = AsyncMongoClient(uri, serverSelectionTimeoutMS=5000, tz_aware=True)
    name = "chainlex_test_audit_" + uuid4().hex
    db = mongo[name]
    settings = Settings(
        _env_file=None,
        analyst_token=SecretStr("analyst-test-token"),
        officer_token=SecretStr("officer-test-token"),
        lease_seconds=10,
        heartbeat_seconds=1,
    )
    await bootstrap(db)
    repo, voyage, reports = AuditRepository(db), TestEmbeddings(), ReportStore(db)
    engine = DurableCompletionAgent(repo, voyage, reports, settings)

    async def retrieve(tenant, clearance, vector, context):
        # Keep transactional tests independent of Atlas indexing latency. A separate
        # live test exercises actual Vector Search and Voyage embeddings.
        docs = [
            doc
            async for doc in db.audit_memories.find(
                memory_filter(tenant, clearance), {"_id": 0, "case_embedding": 0}
            )
        ]
        return {
            "memories": docs,
            "regulations": [],
            "memory_search_status": "complete",
            "regulation_search_status": "complete",
            "embedding_model": "test-double",
        }

    engine.memory.retrieve = retrieve
    memory = GovernedMemoryAgent(repo, voyage)
    app = create_app(settings)
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_memory] = lambda: memory
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as api:
            yield SimpleNamespace(
                db=db,
                repo=repo,
                voyage=voyage,
                reports=reports,
                engine=engine,
                memory=memory,
                settings=settings,
                api=api,
                app=app,
            )
    finally:
        await mongo.drop_database(name)
        await mongo.close()


async def drain(runtime):
    for _ in range(30):
        if not await runtime.engine.run_once("integration-worker"):
            return
    pytest.fail("Audit failed to reach an idle/human checkpoint")


async def start(runtime, scenario="corridor_audit", *, officer=False):
    response = await runtime.api.post(
        "/api/audits",
        headers=OFFICER if officer else ANALYST,
        json={"scenario": scenario, "idempotency_key": uuid4().hex},
    )
    assert response.status_code == 202, response.text
    await drain(runtime)
    return await runtime.repo.get("bank_a", response.json()["audit_id"])


async def approve(runtime, run, *, reject_gate=None):
    for gate in run.gates:
        response = await runtime.api.post(
            f"/api/audits/{run.audit_id}/gates/{gate.gate_id}/decision",
            headers=OFFICER,
            json={
                "decision": "REJECT" if gate.gate_id == reject_gate else "APPROVE",
                "expected_revision": run.revision,
                "analysis_digest": run.analysis_digest,
                "reason": "Reviewed the fictional demo record",
            },
        )
        assert response.status_code == 200, response.text
        run = await runtime.repo.get("bank_a", run.audit_id)
    return run


async def test_api_draft_human_gates_final_pdf_and_tenant_clearance(runtime):
    r = runtime
    run = await start(r)
    assert run.state == AuditState.REVIEW
    assert all(g.status == "PENDING" for g in run.gates)
    assert len(await r.reports.list("bank_a", run.audit_id)) == 1
    endpoint = f"/api/audits/{run.audit_id}/gates/final-signoff/decision"
    payload = {
        "decision": "APPROVE",
        "expected_revision": run.revision,
        "analysis_digest": run.analysis_digest,
        "reason": "Reviewed",
    }
    assert (await r.api.post(endpoint, headers=ANALYST, json=payload)).status_code == 403
    assert (await r.api.post(endpoint, headers=OFFICER, json=payload)).status_code == 409
    await approve(r, run)
    # Reconstruct the worker/service at the human checkpoint, retaining only Atlas state.
    restarted = DurableCompletionAgent(r.repo, r.voyage, r.reports, r.settings)
    await restarted.run_once("restarted-worker")
    run = await r.repo.get("bank_a", run.audit_id)
    assert run.state == AuditState.FINALIZED
    final = await r.api.get(f"/api/audits/{run.audit_id}/reports/2.pdf", headers=ANALYST)
    assert final.status_code == 200
    text = "\n".join(p.extract_text() for p in PdfReader(BytesIO(final.content)).pages)
    assert "REVIEWED_FINAL" in text and "APPROVED" in text
    exported = (await r.api.get(f"/api/audits/{run.audit_id}/export", headers=ANALYST)).json()
    assert exported["audit_chain_valid"]
    assert exported["reports"][-1]["verified"] is True
    assert await r.db.audit_report_files.files.count_documents({}) == 2
    assert await r.db.simulator_operations.count_documents({}) == 0
    assert [t for _, t in r.voyage.calls] == ["query"]
    r.app.dependency_overrides[current_principal] = lambda: Principal(
        tenant_id="bank_b", role="analyst"
    )
    for suffix in ("", "/events", "/reports", "/reports/2.pdf", "/export"):
        assert (await r.api.get(f"/api/audits/{run.audit_id}{suffix}")).status_code == 404
    r.app.dependency_overrides.pop(current_principal)
    privileged = await start(r, officer=True)
    for suffix in ("", "/events", "/reports", "/reports/1.pdf", "/export"):
        assert (
            await r.api.get(f"/api/audits/{privileged.audit_id}{suffix}", headers=ANALYST)
        ).status_code == 404


async def test_memory_correction_invalidation_stale_gates_and_preserved_versions(runtime):
    r = runtime
    run = await start(r, "memory_influence")
    assert run.checkpoint["analysis"]["memory_comparison"]["behavior_changed"] is True
    assert any(g.gate_id.startswith("memory-") for g in run.gates)
    original_pdf = await r.reports.download("bank_a", run.audit_id, 1)
    memory = await r.memory.get("bank_a", "demo-intermediary-review")
    correction = {
        "expected_version": 1,
        "reason": "Correct the fictional precedent",
        "narrative": "A corrected fictional audit requires additional originator documentation.",
        "route_id": "discovered-ca-sg",
        "required_gate": "Confirm originator documents",
        "valid_until": (utcnow() + timedelta(days=5)).isoformat(),
    }
    response = await r.api.post(
        "/api/memories/demo-intermediary-review/correct", json=correction, headers=OFFICER
    )
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    assert (await r.db.audit_memories.find_one({"_id": memory["_id"]}))["is_active"] is False
    stale = await r.api.post(
        f"/api/audits/{run.audit_id}/gates/evidence-review/decision",
        headers=OFFICER,
        json={
            "decision": "APPROVE",
            "expected_revision": run.revision,
            "analysis_digest": run.analysis_digest,
            "reason": "Old snapshot",
        },
    )
    assert stale.status_code == 409
    await drain(r)
    refreshed = await r.repo.get("bank_a", run.audit_id)
    assert refreshed.analysis_digest != run.analysis_digest
    assert refreshed.checkpoint["evidence"]["memories"][0]["version"] == 2
    assert await r.reports.download("bank_a", run.audit_id, 1) == original_pdf
    result = await r.api.post(
        "/api/memories/demo-intermediary-review/invalidate",
        headers=OFFICER,
        json={"expected_version": 2, "reason": "Precedent withdrawn"},
    )
    assert result.status_code == 200
    await drain(r)
    run = await r.repo.get("bank_a", run.audit_id)
    assert run.checkpoint["evidence"]["memories"] == []
    assert run.checkpoint["analysis"]["memory_comparison"]["behavior_changed"] is False
    assert (await r.api.get("/api/memories", headers=ANALYST)).json() == []
    assert len((await r.api.get("/api/memories", headers=OFFICER)).json()) == 2


async def test_pause_action_denial_and_fenced_lease(runtime):
    r = runtime
    run = await r.repo.create("bank_a", "bank_a:analyst", 1, CreateAudit(idempotency_key="pause"))
    assert (
        await r.api.post("/api/control", headers=OFFICER, json={"paused": True})
    ).status_code == 200
    assert not await r.engine.run_once("worker")
    assert r.voyage.calls == []
    await r.api.post("/api/control", headers=OFFICER, json={"paused": False})
    old = await r.repo.claim("old-worker")
    await r.db.compliance_fsms.update_one(
        {"fsm_id": run.audit_id}, {"$set": {"lease_expires_at": utcnow() - timedelta(seconds=1)}}
    )
    new = await r.repo.claim("new-worker")
    assert new.fencing_token > old.fencing_token
    with pytest.raises(AuditConflict):
        await r.repo.authorize(old, "durable_completion", "ADAPT_CONTEXT")
    await r.repo.release(new)
    await r.db.agent_identities.update_one(
        {"tenant_id": "bank_a", "agent_id": "durable_completion"}, {"$set": {"is_active": False}}
    )
    await r.engine.run_once("worker")
    run = await r.repo.get("bank_a", run.audit_id)
    assert run.state == AuditState.MANUAL
    assert r.voyage.calls == []
    history = await r.repo.events("bank_a", run.audit_id)
    assert any(e["event_type"] == "ACTION_DENIED" for e in history)
    assert verify_ledger(history)


async def test_lost_publication_response_recovers_without_duplicate_report(runtime):
    r = runtime
    run = await r.repo.create(
        "bank_a", "bank_a:analyst", 1, CreateAudit(idempotency_key="lost-response")
    )
    for _ in range(4):
        await r.engine.run_once("worker")
    assert (await r.repo.get("bank_a", run.audit_id)).state == AuditState.DRAFT
    original = r.reports.publish

    async def lost_response(*args):
        await original(*args)
        raise httpx.ReadError("Injected loss after successful upload")

    r.reports.publish = lost_response
    await r.engine.run_once("worker")
    waiting = await r.repo.get("bank_a", run.audit_id)
    assert waiting.state == AuditState.RETRY
    assert await r.db.audit_reports.count_documents({}) == 0
    assert await r.db.audit_report_files.files.count_documents({}) == 1
    await r.db.compliance_fsms.update_one(
        {"fsm_id": run.audit_id}, {"$set": {"next_attempt_at": utcnow() - timedelta(seconds=1)}}
    )
    r.engine = DurableCompletionAgent(r.repo, r.voyage, ReportStore(r.db), r.settings)
    await drain(r)
    assert (await r.repo.get("bank_a", run.audit_id)).state == AuditState.REVIEW
    assert await r.db.audit_reports.count_documents({}) == 1
    assert await r.db.audit_report_files.files.count_documents({}) == 1
    assert [t for _, t in r.voyage.calls] == ["query"]


async def test_idempotency_human_rejection_no_route_and_schema_adapters(runtime):
    r = runtime
    request = CreateAudit(idempotency_key="same-input")
    created = await asyncio.gather(
        *(r.repo.create("bank_a", "bank_a:analyst", 1, request) for _ in range(3))
    )
    assert len({a.audit_id for a in created}) == 1
    with pytest.raises(AuditConflict):
        await r.repo.create(
            "bank_a",
            "bank_a:analyst",
            1,
            CreateAudit(idempotency_key="same-input", scenario="no_suitable_route"),
        )
    run = await start(r, "no_suitable_route")
    assert run.checkpoint["analysis"]["recommended_route_id"] is None
    await approve(r, run, reject_gate="evidence-review")
    await drain(r)
    snapshot = (await r.db.audit_reports.find_one({"audit_id": run.audit_id, "version": 2}))[
        "snapshot"
    ]
    assert snapshot["verdict"] == "HUMAN_REJECTED"
    supported = await start(r, "schema_change")
    assert supported.state == AuditState.REVIEW
    assert "v2" in supported.checkpoint["context"]["adapter"]
    unsupported = await start(r, "unsupported_schema")
    assert unsupported.state == AuditState.MANUAL
    assert unsupported.error_code == "SOURCE_SCHEMA_NOT_SUPPORTED"
    retry = await r.api.post(
        f"/api/audits/{unsupported.audit_id}/retry",
        headers=OFFICER,
        json={"expected_revision": unsupported.revision, "reason": "Try again"},
    )
    assert retry.status_code == 409


async def test_policy_proposal_requires_officer_and_rechecks_existing_audit(runtime):
    r = runtime
    run = await start(r)
    proposal = await r.api.post(
        "/api/agent-policies/proposals",
        headers=ANALYST,
        json={
            "expected_version": 1,
            "reason": "Review unavailable corridors",
            "blocked_route_ids": ["configured-ca-us-sg", "discovered-ca-sg"],
        },
    )
    assert proposal.status_code == 201
    endpoint = f"/api/agent-policies/proposals/{proposal.json()['proposal_id']}/decision"
    body = {"decision": "APPROVE", "expected_version": 1, "reason": "Approved restriction"}
    assert (await r.api.post(endpoint, headers=ANALYST, json=body)).status_code == 403
    approved = await r.api.post(endpoint, headers=OFFICER, json=body)
    assert approved.status_code == 200, approved.text
    assert approved.json()["policy_version"] == 2
    await drain(r)
    refreshed = await r.repo.get("bank_a", run.audit_id)
    assert refreshed.analysis_digest != run.analysis_digest
    assert refreshed.checkpoint["analysis"]["recommended_route_id"] is None
    assert all(g.status == "PENDING" for g in refreshed.gates)


async def test_identity_revoked_between_advisory_read_and_transaction_denies_tool(runtime):
    r = runtime
    run = await r.repo.create(
        "bank_a", "bank_a:analyst", 1, CreateAudit(idempotency_key="revoke-race")
    )
    original = r.repo.commit
    revoked = False

    async def raced_commit(*args, **kwargs):
        nonlocal revoked
        if args[1] == "ACTION_PERMITTED" and not revoked:
            revoked = True
            await r.db.agent_identities.update_one(
                {"tenant_id": "bank_a", "agent_id": "durable_completion"},
                {"$set": {"is_active": False}},
            )
        return await original(*args, **kwargs)

    r.repo.commit = raced_commit
    await r.engine.run_once("race-worker")
    history = await r.repo.events("bank_a", run.audit_id)
    assert not any(e["event_type"] == "ACTION_PERMITTED" for e in history)
    assert any(e["event_type"] == "ACTION_DENIED" for e in history)
    assert r.voyage.calls == []


async def test_completed_upload_reconciles_while_paused_and_artifacts_survive_refresh(runtime):
    r = runtime
    run = await r.repo.create(
        "bank_a", "bank_a:analyst", 1, CreateAudit(idempotency_key="pause-recovery")
    )
    for _ in range(4):
        await r.engine.run_once("worker")
    evidence_artifact = await r.db.audit_artifacts.find_one(
        {"audit_id": run.audit_id, "kind": "EVIDENCE_SAVED"}
    )
    assert evidence_artifact["content_hash"] == digest(evidence_artifact["data"])
    original = r.reports.publish

    async def lose_response(*args):
        await original(*args)
        raise httpx.ReadError("Injected lost upload response")

    r.reports.publish = lose_response
    await r.engine.run_once("worker")
    r.reports.publish = original
    await r.api.post("/api/control", headers=OFFICER, json={"paused": True})
    original_probe = r.reports.probe

    async def failed_probe(*args):
        raise httpx.ReadError("Injected transient probe failure while paused")

    r.reports.probe = failed_probe
    await r.engine.run_once("reconciler")
    failed = await r.repo.get("bank_a", run.audit_id)
    assert failed.resume_state == AuditState.DRAFT
    r.reports.probe = original_probe
    await r.engine.run_once("reconciler")
    paused = await r.repo.get("bank_a", run.audit_id)
    assert paused.checkpoint["publication"]["receipt"]["verified"]
    assert not await r.engine.run_once("reconciler")
    assert await r.db.audit_reports.count_documents({}) == 0
    events = await r.repo.events("bank_a", run.audit_id)
    assert events[-1]["event_type"] == "PUBLICATION_RECONCILED"
    assert events[-1]["payload"]["reconciliation_only"] is True
    await r.api.post("/api/control", headers=OFFICER, json={"paused": False})
    await r.db.compliance_fsms.update_one(
        {"fsm_id": run.audit_id}, {"$set": {"next_attempt_at": utcnow() - timedelta(seconds=1)}}
    )
    await drain(r)
    artifacts = [a async for a in r.db.audit_artifacts.find({"audit_id": run.audit_id})]
    assert all(a["content_hash"] == digest(a["data"]) for a in artifacts)
    assert any(a["kind"] == "PUBLICATION_RECONCILED" for a in artifacts)
    assert (
        await r.db.audit_artifacts.find_one({"_id": evidence_artifact["_id"]}) == evidence_artifact
    )


async def test_memory_index_lag_retries_without_canning_a_memoryless_result(runtime):
    r = runtime
    run = await r.repo.create(
        "bank_a",
        "bank_a:analyst",
        1,
        CreateAudit(idempotency_key="index-lag", scenario="memory_influence"),
    )
    original_retrieve = r.engine.memory.retrieve

    async def lagged(tenant, clearance, vector, context):
        return {
            "memories": [],
            "regulations": [],
            "memory_search_status": "complete",
            "regulation_search_status": "complete",
        }

    r.engine.memory.retrieve = lagged
    for _ in range(3):
        await r.engine.run_once("worker")
    waiting = await r.repo.get("bank_a", run.audit_id)
    assert waiting.state == AuditState.RETRY
    assert waiting.error_code == "MemoryIndexPending"
    assert "analysis" not in waiting.checkpoint
    assert [kind for _, kind in r.voyage.calls] == ["query", "document"]
    r.engine.memory.retrieve = original_retrieve
    await r.db.compliance_fsms.update_one(
        {"fsm_id": run.audit_id}, {"$set": {"next_attempt_at": utcnow() - timedelta(seconds=1)}}
    )
    await drain(r)
    completed = await r.repo.get("bank_a", run.audit_id)
    assert completed.checkpoint["analysis"]["memory_comparison"]["behavior_changed"]
    assert [kind for _, kind in r.voyage.calls] == ["query", "document"]
    await r.memory.correct(
        "bank_a",
        "bank_a:officer",
        "demo-intermediary-review",
        MemoryCorrection(
            expected_version=1,
            reason="Corrected demo source",
            narrative="Corrected fictional intermediary precedent",
            route_id="configured-ca-us-sg",
            required_gate="Obtain corrected intermediary documents",
            valid_until=utcnow() + timedelta(days=1),
        ),
    )
    r.engine.memory.retrieve = lagged
    await r.engine.run_once("worker")  # Refresh the old reviewed snapshot.
    await r.engine.run_once("worker")  # Active v2 is still absent from Vector Search.
    corrected_wait = await r.repo.get("bank_a", run.audit_id)
    assert corrected_wait.state == AuditState.RETRY
    assert corrected_wait.error_code == "MemoryIndexPending"


async def test_agent_policy_proposals_preserve_rejection_and_use_new_base_versions(runtime):
    r = runtime
    run = await start(r, "no_suitable_route")
    first = run.checkpoint["analysis"]["policy_proposal"]["proposal_id"]
    decision = await r.api.post(
        f"/api/agent-policies/proposals/{first}/decision",
        headers=OFFICER,
        json={"decision": "REJECT", "expected_version": 1, "reason": "Demo review rejection"},
    )
    assert decision.status_code == 200, decision.text
    await r.api.post("/api/control", headers=OFFICER, json={"paused": True})
    await r.api.post("/api/control", headers=OFFICER, json={"paused": False})
    await drain(r)
    refreshed = await r.repo.get("bank_a", run.audit_id)
    assert refreshed.checkpoint["analysis"]["policy_proposal"]["proposal_id"] == first
    assert refreshed.checkpoint["analysis"]["policy_proposal"]["status"] == "REJECTED"
    separate = await r.api.post(
        "/api/agent-policies/proposals",
        headers=ANALYST,
        json={
            "expected_version": 1,
            "reason": "Independent reviewed policy update",
            "blocked_route_ids": [],
        },
    )
    approved = await r.api.post(
        f"/api/agent-policies/proposals/{separate.json()['proposal_id']}/decision",
        headers=OFFICER,
        json={
            "decision": "APPROVE",
            "expected_version": 1,
            "reason": "Approve independent version",
        },
    )
    assert approved.status_code == 200
    await drain(r)
    current = await r.repo.get("bank_a", run.audit_id)
    latest = current.checkpoint["analysis"]["policy_proposal"]["proposal_id"]
    assert latest != first
    stored = await r.db.audit_policy_proposals.find_one(
        {"proposal_id": latest, "tenant_id": "bank_a"}
    )
    assert stored["expected_version"] == 2 and stored["status"] == "PENDING"
    response = await r.api.post(
        f"/api/agent-policies/proposals/{latest}/decision",
        headers=OFFICER,
        json={"decision": "APPROVE", "expected_version": 2, "reason": "Approve restriction"},
    )
    assert response.status_code == 200, response.text
