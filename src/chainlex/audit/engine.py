"""Durable Completion Agent: restartable audit steps and verified publication."""

import asyncio
import contextlib
import logging
from datetime import timedelta
from email.utils import parsedate_to_datetime

import httpx

from chainlex.audit.agents import AGENT_DESCRIPTIONS, AuditableActionAgent
from chainlex.audit.memory import GovernedMemoryAgent, MemoryIndexPending, eligible_memory
from chainlex.audit.models import (
    ActionDenied,
    AgentId,
    AuditConflict,
    AuditState,
    HumanGate,
    UnsupportedSchema,
    WorkflowPaused,
    digest,
    utcnow,
)
from chainlex.audit.scenarios import adapt_context

logger = logging.getLogger(__name__)


def retry_delay(exc, attempt):
    delay = min(2**attempt, 60)
    if isinstance(exc, httpx.HTTPStatusError):
        header = exc.response.headers.get("Retry-After")
        if header:
            try:
                delay = max(delay, float(header))
            except ValueError:
                try:
                    delay = max(delay, (parsedate_to_datetime(header) - utcnow()).total_seconds())
                except (ValueError, TypeError):
                    pass
        elif exc.response.status_code == 429:
            delay = 60
    return min(delay, 60)


class DurableCompletionAgent:
    agent_id = AgentId.COMPLETION

    def __init__(self, repository, voyage, reports, settings):
        self.repo, self.voyage, self.reports, self.settings = repository, voyage, reports, settings
        self.memory = GovernedMemoryAgent(repository, voyage)
        self.action = AuditableActionAgent()

    async def _heartbeat(self, run):
        while True:
            await asyncio.sleep(self.settings.heartbeat_seconds)
            result = await self.repo.heartbeat(run)
            if result.modified_count != 1:
                return

    async def run_once(self, worker_id):
        run = await self.repo.claim(worker_id)
        if run is None:
            return False
        heartbeat = asyncio.create_task(self._heartbeat(run))
        try:
            await self.step(run)
        except WorkflowPaused:
            pass
        except Exception as exc:
            # Only codes reach stored errors/logs, never provider responses or credentials.
            logger.warning(
                "audit_step_failed audit_id=%s error=%s", run.audit_id, type(exc).__name__
            )
            current = await self.repo.get(run.tenant_id, run.audit_id)
            if (
                current.lease_owner == run.lease_owner
                and current.fencing_token == run.fencing_token
            ):
                attempt = current.attempts + 1
                manual = (
                    isinstance(exc, (ActionDenied, UnsupportedSchema))
                    or attempt >= self.settings.max_step_attempts
                )
                changes = {
                    "state": AuditState.MANUAL if manual else AuditState.RETRY,
                    "resume_state": (
                        current.resume_state if current.state == AuditState.RETRY else current.state
                    ),
                    "attempts": attempt,
                    "error_code": "SOURCE_SCHEMA_NOT_SUPPORTED"
                    if isinstance(exc, UnsupportedSchema)
                    else type(exc).__name__,
                    "next_attempt_at": None
                    if manual
                    else utcnow() + timedelta(seconds=retry_delay(exc, attempt)),
                }
                try:
                    await self.repo.commit(
                        current,
                        "MANUAL_REVIEW_REQUIRED" if manual else "STEP_RETRY_SCHEDULED",
                        changes=changes,
                        payload={
                            "failed_state": current.state,
                            "attempt": attempt,
                            "error_code": changes["error_code"],
                        },
                    )
                except AuditConflict:
                    pass
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
            await self.repo.release(run)
        return True

    async def _advance(self, run, state, event, checkpoint, **updates):
        return await self.repo.commit(
            run,
            event,
            changes={
                "state": state,
                "checkpoint": checkpoint,
                "attempts": 0,
                "error_code": None,
                "resume_state": None,
                "next_attempt_at": None,
                **updates,
            },
        )

    async def refresh(self, run):
        checkpoint = {
            k: v
            for k, v in run.checkpoint.items()
            if k in {"source", "context", "query_vector", "draft_receipt"}
        }
        return await self._advance(
            run,
            AuditState.EVIDENCE,
            "DEPENDENCIES_CHANGED",
            checkpoint,
            gates=(),
            analysis_digest=None,
            governance_revision=None,
        )

    async def step(self, run):
        publication = run.checkpoint.get("publication")
        if publication and not publication.get("receipt"):
            receipt = await self.reports.probe(publication["file_id"], publication["snapshot"])
            publication = {
                **publication,
                "receipt": receipt,
                "next_probe_at": utcnow() + timedelta(seconds=self.settings.poll_seconds),
            }
            run = await self.repo.commit(
                run,
                "PUBLICATION_RECONCILED" if receipt else "PUBLICATION_NOT_CONFIRMED",
                changes={"checkpoint": {**run.checkpoint, "publication": publication}},
                payload={
                    "file_id": publication["file_id"],
                    "verified": bool(receipt),
                    "reconciliation_only": True,
                },
            )
        if (await self.repo.controls(run.tenant_id))["paused"]:
            return run
        if run.state == AuditState.RETRY:
            if run.next_attempt_at and run.next_attempt_at > utcnow():
                return run
            return await self._advance(
                run, run.resume_state, "RETRY_DUE", run.checkpoint, attempts=run.attempts
            )
        if run.state == AuditState.RECEIVED:
            run = await self.repo.authorize(run, AgentId.COMPLETION, "ADAPT_CONTEXT")
            context = adapt_context(run.checkpoint["source"])
            return await self._advance(
                run,
                AuditState.EVIDENCE,
                "CONTEXT_VALIDATED",
                {**run.checkpoint, "context": context},
            )
        if run.state == AuditState.EVIDENCE:
            if "query_vector" not in run.checkpoint:
                run = await self.repo.authorize(run, AgentId.MEMORY, "EMBED_QUERY")
                vector = (
                    await self.voyage.embed([run.checkpoint["context"]["narrative"]], "query")
                )[0]
                return await self._advance(
                    run,
                    AuditState.EVIDENCE,
                    "QUERY_EMBEDDED",
                    {**run.checkpoint, "query_vector": vector},
                )
            expected_memory = None
            if run.scenario == "memory_influence":
                # Seed once; invalidation/correction is never undone by subsequent runs.
                expected_memory = await self.memory.ensure_demo(run.tenant_id)
            run = await self.repo.authorize(run, AgentId.MEMORY, "RETRIEVE_EVIDENCE")
            control = await self.repo.controls(run.tenant_id)
            evidence = await self.memory.retrieve(
                run.tenant_id,
                run.clearance_level,
                run.checkpoint["query_vector"],
                run.checkpoint["context"],
            )
            if (
                expected_memory
                and eligible_memory(expected_memory, run.tenant_id, run.clearance_level)
                and not any(
                    m["memory_id"] == expected_memory["memory_id"]
                    and m["version"] == expected_memory["version"]
                    for m in evidence["memories"]
                )
            ):
                raise MemoryIndexPending("Expected demo memory has not reached Vector Search")
            return await self.repo.commit(
                run,
                "EVIDENCE_SAVED",
                actor=AgentId.MEMORY,
                expected_control=control["revision"],
                changes={
                    "state": AuditState.ANALYSIS,
                    "attempts": 0,
                    "checkpoint": {**run.checkpoint, "evidence": evidence},
                    "governance_revision": control["revision"],
                },
            )
        if run.state in {
            AuditState.ANALYSIS,
            AuditState.DRAFT,
            AuditState.REVIEW,
            AuditState.FINAL,
        }:
            control = await self.repo.controls(run.tenant_id)
            try:
                await self.memory.revalidate(
                    run.tenant_id, run.clearance_level, run.checkpoint["evidence"]
                )
                if control["revision"] != run.governance_revision:
                    raise AuditConflict("Governance changed")
            except AuditConflict:
                return await self.refresh(run)
        if run.state == AuditState.ANALYSIS:
            run = await self.repo.authorize(run, AgentId.ACTION, "ASSESS_ROUTES")
            policy = await self.repo.policy(run.tenant_id)
            analysis = self.action.assess(
                run.checkpoint["context"], run.checkpoint["evidence"], policy["blocked_route_ids"]
            )
            denied = {
                r["route_id"] for r in analysis["routes"] if "BANK_ADMISSION_DENIED" in r["issues"]
            }
            proposal = None
            if denied - set(policy["blocked_route_ids"]):
                run = await self.repo.authorize(run, AgentId.ACTION, "PROPOSE_POLICY")
                proposal_input_hash = digest(
                    {
                        "blocked": sorted(denied | set(policy["blocked_route_ids"])),
                        "evidence": run.checkpoint["evidence"],
                        "context": run.checkpoint["context"],
                    }
                )
                proposal = {
                    "proposal_id": (
                        f"policy-{run.audit_id}-v{policy['version']}-{proposal_input_hash[:12]}"
                    ),
                    "tenant_id": run.tenant_id,
                    "schema_version": 1,
                    "status": "PENDING",
                    "proposed_by": AgentId.ACTION,
                    "initiated_by": run.initiated_by,
                    "expected_version": policy["version"],
                    "reason": "Proposed demo restriction after explicit bank-admission denial",
                    "blocked_route_ids": sorted(set(policy["blocked_route_ids"]) | denied),
                }
                proposal["proposal_digest"] = digest(proposal)
                existing = await self.repo.db.audit_policy_proposals.find_one(
                    {"tenant_id": run.tenant_id, "proposal_id": proposal["proposal_id"]}, {"_id": 0}
                )
                if existing:
                    proposal = existing
                analysis["policy_proposal"] = {
                    "proposal_id": proposal["proposal_id"],
                    "proposal_digest": proposal["proposal_digest"],
                    "status": (
                        "PENDING_OFFICER_DECISION"
                        if proposal["status"] == "PENDING"
                        else proposal["status"]
                    ),
                }

            async def stage_proposal(session):
                if proposal:
                    await self.repo.db.audit_policy_proposals.update_one(
                        {"tenant_id": run.tenant_id, "proposal_id": proposal["proposal_id"]},
                        {"$setOnInsert": proposal},
                        upsert=True,
                        session=session,
                    )

            analysis_digest = digest(
                {
                    "analysis": analysis,
                    "context": run.checkpoint["context"],
                    "evidence": run.checkpoint["evidence"],
                    "policy_version": policy["version"],
                }
            )
            return await self.repo.commit(
                run,
                "ANALYSIS_VALIDATED",
                actor=AgentId.ACTION,
                expected_control=run.governance_revision,
                extra=stage_proposal,
                changes={
                    "state": AuditState.DRAFT,
                    "attempts": 0,
                    "analysis_digest": analysis_digest,
                    "checkpoint": {
                        **run.checkpoint,
                        "analysis": analysis,
                        "policy_version": policy["version"],
                        "policy_snapshot": {k: v for k, v in policy.items() if k != "_id"},
                    },
                    "gates": tuple(HumanGate.model_validate(g) for g in analysis["gates"]),
                },
            )
        if run.state in {AuditState.DRAFT, AuditState.FINAL}:
            return await self._publish(run)
        return run

    async def _publish(self, run):
        final = run.state == AuditState.FINAL
        kind = "REVIEWED_FINAL" if final else "DRAFT"
        publication = run.checkpoint.get("publication")
        if not publication or not publication.get("receipt"):
            run = await self.repo.authorize(
                run, AgentId.COMPLETION, "PUBLISH_FINAL" if final else "PUBLISH_DRAFT"
            )
        if publication is None:
            existing = await self.reports.list(run.tenant_id, run.audit_id)
            version = max((r["version"] for r in existing), default=0) + 1
            analysis = run.checkpoint["analysis"]
            rejected = any(g.status == "REJECTED" for g in run.gates)
            snapshot = {
                "tenant_id": run.tenant_id,
                "audit_id": run.audit_id,
                "kind": kind,
                "version": version,
                "mode": run.mode,
                "created_at": utcnow().isoformat(),
                "initiated_by": run.initiated_by,
                "analysis_digest": run.analysis_digest,
                "analysis": analysis,
                "context": run.checkpoint["context"],
                "policy": run.checkpoint.get("policy_snapshot", {}),
                "evidence": run.checkpoint["evidence"],
                "gates": [g.model_dump(mode="json") for g in run.gates],
                "agents": [{"agent_id": a, **d} for a, d in AGENT_DESCRIPTIONS.items()],
                "events": await self.repo.events(run.tenant_id, run.audit_id),
                "verdict": "HUMAN_REJECTED" if rejected and final else analysis["verdict"],
            }
            if analysis.get("policy_proposal"):
                proposal_record = await self.repo.db.audit_policy_proposals.find_one(
                    {
                        "tenant_id": run.tenant_id,
                        "proposal_id": analysis["policy_proposal"]["proposal_id"],
                    },
                    {"_id": 0},
                )
                snapshot["policy_proposal"] = proposal_record
            publication = {
                "snapshot": snapshot,
                "version": version,
                "attempt_fence": run.fencing_token,
                "file_id": f"{run.tenant_id}:{run.audit_id}:v{version}:f{run.fencing_token}",
            }
            run = await self.repo.commit(
                run,
                "REPORT_PREPARED",
                changes={"checkpoint": {**run.checkpoint, "publication": publication}},
                expected_control=run.governance_revision,
                payload={"kind": kind, "version": version, "snapshot_hash": digest(snapshot)},
            )
        elif publication["attempt_fence"] != run.fencing_token and not await self.reports.exists(
            publication["file_id"]
        ):
            # An interrupted GridFS upload may leave chunks without a completed file.
            # Keep that attempt isolated; publish under a new saved identity and fence.
            publication = {
                **publication,
                "attempt_fence": run.fencing_token,
                "file_id": (
                    f"{run.tenant_id}:{run.audit_id}:v{publication['version']}:f{run.fencing_token}"
                ),
            }
            run = await self.repo.commit(
                run,
                "PUBLICATION_RECOVERY_PREPARED",
                changes={"checkpoint": {**run.checkpoint, "publication": publication}},
                expected_control=run.governance_revision,
            )
        receipt = publication.get("receipt")
        if not receipt:
            receipt = await self.reports.publish(
                run.tenant_id,
                run.audit_id,
                publication["version"],
                publication["snapshot"],
                publication["file_id"],
            )
        manifest = {
            "tenant_id": run.tenant_id,
            "schema_version": 1,
            "audit_id": run.audit_id,
            "version": publication["version"],
            "kind": kind,
            "analysis_digest": run.analysis_digest,
            "snapshot": publication["snapshot"],
            "published_at": utcnow(),
            **receipt,
        }

        async def record(session):
            await self.memory.revalidate(
                run.tenant_id, run.clearance_level, run.checkpoint["evidence"], session=session
            )
            await self.repo.db.audit_reports.insert_one(dict(manifest), session=session)

        checkpoint = {k: v for k, v in run.checkpoint.items() if k != "publication"}
        checkpoint["final_receipt" if final else "draft_receipt"] = {
            "version": manifest["version"],
            "kind": kind,
            **receipt,
        }
        return await self.repo.commit(
            run,
            "FINAL_REPORT_VERIFIED" if final else "DRAFT_REPORT_VERIFIED",
            changes={
                "state": AuditState.FINALIZED if final else AuditState.REVIEW,
                "attempts": 0,
                "checkpoint": checkpoint,
            },
            expected_control=run.governance_revision,
            extra=record,
            payload={
                "version": manifest["version"],
                "sha256": receipt["sha256"],
                "file_id": receipt["file_id"],
                "verified": True,
            },
        )
