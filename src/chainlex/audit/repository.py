"""Transactional audit snapshots, fenced worker ownership and hash-linked events."""

from datetime import timedelta
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from chainlex.audit.models import (
    ACTIVE_STATES,
    ActionDenied,
    AgentId,
    AuditConflict,
    AuditNotFound,
    AuditRun,
    AuditState,
    CreateAudit,
    WorkflowPaused,
    digest,
    utcnow,
)
from chainlex.audit.scenarios import SCENARIOS, scenario_input

AGENT_ACTIONS = {
    AgentId.ACTION: ("ASSESS_ROUTES", "PROPOSE_POLICY"),
    AgentId.MEMORY: ("EMBED_QUERY", "EMBED_MEMORY", "RETRIEVE_EVIDENCE"),
    AgentId.COMPLETION: ("ADAPT_CONTEXT", "PUBLISH_DRAFT", "PUBLISH_FINAL"),
}


def ledger_event(tenant, fsm_id, sequence, event_type, actor, previous_hash, payload):
    event = {
        "tenant_id": tenant,
        "schema_version": 1,
        "fsm_id": fsm_id,
        "sequence": sequence,
        "event_id": uuid4().hex,
        "event_type": event_type,
        "actor_id": actor,
        "occurred_at": utcnow().isoformat(),
        "previous_hash": previous_hash,
        "payload": payload,
    }
    event["record_hash"] = digest(event)
    return event


def verify_ledger(events: list[dict], *, expected_last_hash=None, expected_sequence=None) -> bool:
    previous = "0" * 64
    for sequence, event in enumerate(events, 1):
        raw = {k: v for k, v in event.items() if k not in {"_id", "record_hash"}}
        if (
            event["sequence"] != sequence
            or event["previous_hash"] != previous
            or digest(raw) != event["record_hash"]
        ):
            return False
        previous = event["record_hash"]
    return (expected_last_hash is None or previous == expected_last_hash) and (
        expected_sequence is None or len(events) == expected_sequence
    )


class AuditRepository:
    def __init__(self, database, lease_seconds: int = 10):
        self.db = database
        self.lease_seconds = lease_seconds

    async def ensure_tenant(self, tenant: str):
        initialized = await self.db.tenant_controls.find_one({"tenant_id": tenant})
        if initialized and initialized.get("audit_bootstrap_version") == 1:
            return
        await self.db.tenant_controls.update_one(
            {"tenant_id": tenant},
            {
                "$setOnInsert": {
                    "tenant_id": tenant,
                    "schema_version": 1,
                    "paused": False,
                    "revision": 1,
                    "audit_sequence": 0,
                    "governance_hash": "0" * 64,
                    "policy_version": 1,
                }
            },
            upsert=True,
        )
        for agent in AGENT_ACTIONS:
            await self.db.agent_identities.update_one(
                {"tenant_id": tenant, "agent_id": agent},
                {
                    "$setOnInsert": {
                        "tenant_id": tenant,
                        "schema_version": 1,
                        "agent_id": agent,
                        "is_active": True,
                        "mode": "scripted_demo",
                        "delegated_by": "demo-bootstrap",
                    }
                },
                upsert=True,
            )
        await self.db.policies.update_one(
            {"_id": f"{tenant}:audit-agents:v1"},
            {
                "$setOnInsert": {
                    "tenant_id": tenant,
                    "schema_version": 1,
                    "policy_type": "AUDIT_AGENT_POLICY",
                    "version": 1,
                    "mode": "scripted_demo",
                    "allowed_actions": AGENT_ACTIONS,
                    "blocked_route_ids": [],
                    "approved_by": "demo-bootstrap",
                }
            },
            upsert=True,
        )
        for name in SCENARIOS:
            await self.db.audit_scenarios.update_one(
                {"tenant_id": tenant, "scenario_id": name},
                {
                    "$setOnInsert": {
                        "tenant_id": tenant,
                        "schema_version": 1,
                        "scenario_id": name,
                        "source": scenario_input(name),
                        "mode": "scripted_demo",
                        "is_demo_fixture": True,
                    }
                },
                upsert=True,
            )
        await self.db.tenant_controls.update_one(
            {"tenant_id": tenant}, {"$set": {"audit_bootstrap_version": 1}}
        )

    async def controls(self, tenant: str, *, session=None):
        control = await self.db.tenant_controls.find_one({"tenant_id": tenant}, session=session)
        if control is None:
            raise AuditConflict("Tenant controls are not initialized")
        return control

    async def policy(self, tenant: str, *, session=None):
        control = await self.controls(tenant, session=session)
        policy = await self.db.policies.find_one(
            {
                "tenant_id": tenant,
                "policy_type": "AUDIT_AGENT_POLICY",
                "version": control["policy_version"],
            },
            session=session,
        )
        if policy is None:
            raise ActionDenied("AGENT_POLICY_MISSING")
        return policy

    async def get(self, tenant: str, audit_id: str) -> AuditRun:
        doc = await self.db.compliance_fsms.find_one(
            {"tenant_id": tenant, "fsm_id": audit_id, "workflow_type": "AUDIT"},
            {"_id": 0},
        )
        if doc is None:
            raise AuditNotFound("Audit not found")
        return AuditRun.model_validate(doc)

    async def create(self, tenant: str, actor: str, clearance: int, request: CreateAudit):
        await self.ensure_tenant(tenant)
        if request.previous_audit_id:
            await self.get(tenant, request.previous_audit_id)
        existing = await self.db.compliance_fsms.find_one(
            {"tenant_id": tenant, "idempotency_key": request.idempotency_key}
        )
        if existing:
            if (
                existing.get("workflow_type") != "AUDIT"
                or existing["scenario"] != request.scenario
                or existing.get("previous_audit_id") != request.previous_audit_id
            ):
                raise AuditConflict("Idempotency key already has different inputs")
            return await self.get(tenant, existing["fsm_id"])
        identity = "audit-" + uuid4().hex
        scenario = await self.db.audit_scenarios.find_one(
            {"tenant_id": tenant, "scenario_id": request.scenario}
        )
        if scenario is None:
            raise AuditNotFound("Demo scenario is unavailable")
        run = AuditRun(
            audit_id=identity,
            fsm_id=identity,
            tenant_id=tenant,
            initiated_by=actor,
            clearance_level=clearance,
            scenario=request.scenario,
            idempotency_key=request.idempotency_key,
            previous_audit_id=request.previous_audit_id,
            checkpoint={"source": scenario["source"]},
        )
        event = ledger_event(
            tenant,
            identity,
            1,
            "AUDIT_REQUESTED",
            actor,
            "0" * 64,
            {"scenario": request.scenario, "mode": run.mode},
        )
        run = run.model_copy(update={"last_event_hash": event["record_hash"]})

        async def create(session):
            await self.db.compliance_fsms.insert_one(run.model_dump(mode="python"), session=session)
            await self.db.audit_ledger.insert_one(dict(event), session=session)

        try:
            async with self.db.client.start_session() as session:
                await session.with_transaction(create)
        except DuplicateKeyError:
            return await self.create(tenant, actor, clearance, request)
        return run

    async def commit(
        self,
        run: AuditRun,
        event_type: str,
        *,
        changes=None,
        payload=None,
        actor: str = AgentId.COMPLETION,
        fenced: bool = True,
        expected_control: int | None = None,
        permit: bool = False,
        extra=None,
        permit_guard=None,
    ) -> AuditRun:
        async def update(session):
            current = await self.db.compliance_fsms.find_one(
                {
                    "tenant_id": run.tenant_id,
                    "fsm_id": run.audit_id,
                    "workflow_type": "AUDIT",
                    "revision": run.revision,
                },
                session=session,
            )
            if current is None:
                raise AuditConflict("Audit revision changed")
            now = utcnow()
            if fenced and (
                current.get("lease_owner") != run.lease_owner
                or current.get("fencing_token") != run.fencing_token
                or current.get("lease_expires_at") is None
                or current["lease_expires_at"] <= now
                or run.lease_owner is None
            ):
                raise AuditConflict("Worker lease expired or was replaced")
            control = await self.controls(run.tenant_id, session=session)
            if expected_control is not None and control["revision"] != expected_control:
                raise AuditConflict("Governance changed; refresh evidence and decisions")
            if permit and control["paused"]:
                raise WorkflowPaused("Tenant is paused")
            if permit and permit_guard:
                await permit_guard(session, control)
            if permit or expected_control is not None:
                await self.db.tenant_controls.update_one(
                    {"tenant_id": run.tenant_id, "revision": control["revision"]},
                    {"$inc": {"action_serial": 1}},
                    session=session,
                )
            updates = {"revision": run.revision + 1, "updated_at": now, **(changes or {})}
            if fenced:
                updates["lease_expires_at"] = now + timedelta(seconds=self.lease_seconds)
            artifact = None
            event_payload = dict(payload or {})
            if changes and "checkpoint" in changes:
                artifact = {
                    "tenant_id": run.tenant_id,
                    "schema_version": 1,
                    "audit_id": run.audit_id,
                    "artifact_id": f"{run.audit_id}:r{updates['revision']}",
                    "revision": updates["revision"],
                    "kind": event_type,
                    "data": changes["checkpoint"],
                    "content_hash": digest(changes["checkpoint"]),
                }
                event_payload["artifact"] = {
                    "artifact_id": artifact["artifact_id"],
                    "content_hash": artifact["content_hash"],
                }
            event = ledger_event(
                run.tenant_id,
                run.audit_id,
                updates["revision"],
                event_type,
                str(actor),
                run.last_event_hash,
                {
                    "initiated_by": run.initiated_by,
                    "governance_revision": control["revision"],
                    **event_payload,
                },
            )
            updates["last_event_hash"] = event["record_hash"]
            result = AuditRun.model_validate(
                {**{k: v for k, v in current.items() if k != "_id"}, **updates}
            )
            await self.db.compliance_fsms.replace_one(
                {"_id": current["_id"], "revision": run.revision},
                result.model_dump(mode="python"),
                session=session,
            )
            await self.db.audit_ledger.insert_one(dict(event), session=session)
            if artifact:
                await self.db.audit_artifacts.insert_one(dict(artifact), session=session)
            if extra:
                await extra(session)
            return result

        async with self.db.client.start_session() as session:
            return await session.with_transaction(update)

    async def authorize(self, run: AuditRun, agent: AgentId, action: str) -> AuditRun:
        # A policy check outside a transaction is advisory: commit serializes its
        # permit against the exact governance revision before any tool is invoked.
        control = await self.controls(run.tenant_id)
        if run.governance_revision is not None and control["revision"] != run.governance_revision:
            raise AuditConflict("Analysis dependencies changed before the action permit")
        policy = await self.policy(run.tenant_id)
        identity = await self.db.agent_identities.find_one(
            {"tenant_id": run.tenant_id, "agent_id": agent, "is_active": True}
        )
        allowed = bool(identity and action in policy["allowed_actions"].get(agent, []))

        async def check_identity(session, current_control):
            current_policy = await self.policy(run.tenant_id, session=session)
            result = await self.db.agent_identities.update_one(
                {
                    "tenant_id": run.tenant_id,
                    "agent_id": agent,
                    "is_active": True,
                    "delegated_by": identity["delegated_by"],
                },
                {"$inc": {"permit_serial": 1}},
                session=session,
            )
            if result.modified_count != 1 or action not in current_policy["allowed_actions"].get(
                agent, []
            ):
                raise ActionDenied("Identity or policy revoked before permit")

        try:
            result = await self.commit(
                run,
                "ACTION_PERMITTED" if allowed else "ACTION_DENIED",
                actor=agent,
                expected_control=control["revision"],
                permit=allowed,
                permit_guard=check_identity,
                payload={
                    "action": action,
                    "agent_id": agent,
                    "policy_version": policy["version"],
                    "policy_digest": digest({k: v for k, v in policy.items() if k != "_id"}),
                    "authority": identity.get("delegated_by") if identity else None,
                    "input_digest": digest(run.checkpoint),
                    "allowed": allowed,
                },
            )
        except ActionDenied:
            await self.commit(
                run,
                "ACTION_DENIED",
                actor=agent,
                payload={
                    "action": action,
                    "agent_id": agent,
                    "allowed": False,
                    "policy_version": policy["version"],
                    "authority": None,
                    "input_digest": digest(run.checkpoint),
                },
            )
            raise
        if not allowed:
            raise ActionDenied("AGENT_ACTION_NOT_PERMITTED")
        return result

    async def claim(self, worker: str):
        now = utcnow()
        cursor = self.db.compliance_fsms.find(
            {
                "workflow_type": "AUDIT",
                "$and": [
                    {
                        "$or": [
                            {"state": {"$in": list(ACTIVE_STATES)}},
                            {"state": AuditState.REVIEW},
                            {"state": AuditState.RETRY, "next_attempt_at": {"$lte": now}},
                            {
                                "state": AuditState.RETRY,
                                "checkpoint.publication": {"$exists": True},
                            },
                        ]
                    },
                    {"$or": [{"lease_expires_at": None}, {"lease_expires_at": {"$lte": now}}]},
                ],
            }
        ).sort("updated_at", 1)
        async for candidate in cursor:
            control = await self.controls(candidate["tenant_id"])
            publication = candidate["checkpoint"].get("publication")
            early_retry = (
                candidate["state"] == AuditState.RETRY
                and candidate.get("next_attempt_at")
                and candidate["next_attempt_at"] > now
            )
            if control["paused"] or early_retry:
                if (
                    not publication
                    or publication.get("receipt")
                    or publication.get("next_probe_at", now) > now
                ):
                    continue
            if candidate["state"] == AuditState.REVIEW:
                evidence = candidate["checkpoint"].get("evidence", {})
                expiries = [m["valid_until"] for m in evidence.get("memories", [])]
                expiries.extend(
                    r["valid_until"]
                    for r in evidence.get("regulations", [])
                    if r.get("valid_until")
                )
                if candidate.get("governance_revision") == control["revision"] and not any(
                    expiry <= now for expiry in expiries
                ):
                    continue
            doc = await self.db.compliance_fsms.find_one_and_update(
                {
                    "_id": candidate["_id"],
                    "revision": candidate["revision"],
                    "$or": [{"lease_expires_at": None}, {"lease_expires_at": {"$lte": now}}],
                },
                {
                    "$set": {
                        "lease_owner": worker,
                        "lease_expires_at": now + timedelta(seconds=self.lease_seconds),
                    },
                    "$inc": {"fencing_token": 1},
                },
                return_document=ReturnDocument.AFTER,
            )
            if doc:
                return AuditRun.model_validate({k: v for k, v in doc.items() if k != "_id"})
        return None

    async def heartbeat(self, run: AuditRun):
        return await self.db.compliance_fsms.update_one(
            {
                "tenant_id": run.tenant_id,
                "fsm_id": run.audit_id,
                "lease_owner": run.lease_owner,
                "fencing_token": run.fencing_token,
                "lease_expires_at": {"$gt": utcnow()},
            },
            {"$set": {"lease_expires_at": utcnow() + timedelta(seconds=self.lease_seconds)}},
        )

    async def release(self, run: AuditRun):
        await self.db.compliance_fsms.update_one(
            {
                "tenant_id": run.tenant_id,
                "fsm_id": run.audit_id,
                "lease_owner": run.lease_owner,
                "fencing_token": run.fencing_token,
            },
            {"$set": {"lease_owner": None, "lease_expires_at": None}},
        )

    async def events(self, tenant: str, audit_id: str, after_seq: int = 0):
        await self.get(tenant, audit_id)
        return [
            item
            async for item in self.db.audit_ledger.find(
                {"tenant_id": tenant, "fsm_id": audit_id, "sequence": {"$gt": after_seq}},
                {"_id": 0},
            ).sort("sequence", 1)
        ]

    async def governance(
        self,
        tenant: str,
        actor: str,
        event_type: str,
        payload: dict,
        mutate=None,
        *,
        bump: bool = True,
    ):
        await self.ensure_tenant(tenant)

        async def apply(session):
            control = await self.controls(tenant, session=session)
            additional = await mutate(session, control) if mutate else {}
            event = ledger_event(
                tenant,
                f"governance:{tenant}",
                control["audit_sequence"] + 1,
                event_type,
                actor,
                control["governance_hash"],
                payload,
            )
            updates = {"audit_sequence": event["sequence"], "governance_hash": event["record_hash"]}
            updates.update(additional or {})
            await self.db.tenant_controls.update_one(
                {"tenant_id": tenant},
                {"$set": updates, "$inc": {"revision": int(bump)}},
                session=session,
            )
            await self.db.audit_ledger.insert_one(dict(event), session=session)
            return {**control, **updates, "revision": control["revision"] + int(bump)}

        async with self.db.client.start_session() as session:
            return await session.with_transaction(apply)
