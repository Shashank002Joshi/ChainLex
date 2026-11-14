from datetime import timedelta
from types import SimpleNamespace

import httpx

from chainlex.audit.engine import DurableCompletionAgent
from chainlex.audit.memory import GovernedMemoryAgent, eligible_memory
from chainlex.audit.models import AuditRun, AuditState, digest, utcnow
from chainlex.config import Settings


class RecoveryRepository:
    def __init__(self):
        self.db = SimpleNamespace()
        self.run = AuditRun(
            audit_id="audit-recovery",
            fsm_id="audit-recovery",
            tenant_id="bank_a",
            scenario="corridor_audit",
            idempotency_key="recovery",
            initiated_by="bank_a:analyst",
            state=AuditState.RETRY,
            resume_state=AuditState.DRAFT,
            attempts=1,
            next_attempt_at=utcnow() - timedelta(seconds=1),
            checkpoint={"publication": {"file_id": "already-uploaded", "snapshot": {}}},
        )

    async def claim(self, worker):
        self.run = self.run.model_copy(
            update={"lease_owner": worker, "fencing_token": self.run.fencing_token + 1}
        )
        return self.run

    async def get(self, tenant, audit_id):
        return self.run

    async def commit(self, run, event, *, changes=None, **kwargs):
        self.run = AuditRun.model_validate(
            {**run.model_dump(), **(changes or {}), "revision": run.revision + 1}
        )
        return self.run

    async def controls(self, tenant):
        return {"paused": False}

    async def release(self, run):
        pass

    async def heartbeat(self, run):
        return SimpleNamespace(modified_count=1)


async def test_probe_failure_in_retry_preserves_original_business_resume_state():
    repo = RecoveryRepository()

    class Reports:
        failures = 1

        async def probe(self, file_id, snapshot):
            if self.failures:
                self.failures -= 1
                raise httpx.ReadError("Injected transient reconciliation failure")
            return {"file_id": file_id, "verified": True}

    engine = DurableCompletionAgent(repo, None, Reports(), Settings(_env_file=None))
    await engine.run_once("worker")
    assert repo.run.state == AuditState.RETRY
    assert repo.run.resume_state == AuditState.DRAFT
    repo.run = repo.run.model_copy(update={"next_attempt_at": utcnow() - timedelta(seconds=1)})
    await engine.run_once("worker")
    assert repo.run.state == AuditState.DRAFT
    assert repo.run.resume_state is None
    assert repo.run.checkpoint["publication"]["receipt"]["verified"]


async def test_demo_seed_returns_latest_corrected_version_without_recreating_it():
    class Memories:
        async def find_one(self, query, *, sort):
            assert sort == [("version", -1)]
            return {"version": 2, "is_active": True}

    repo = SimpleNamespace(db=SimpleNamespace(audit_memories=Memories()))
    assert (await GovernedMemoryAgent(repo, None).ensure_demo("bank_a"))["version"] == 2


def test_expected_demo_memory_uses_full_retrieval_eligibility():
    now = utcnow()
    memory = {
        "tenant_id": "bank_a",
        "scope": "scripted_demo",
        "is_active": True,
        "review_status": "REVIEWED_DEMO",
        "clearance_level": 1,
        "valid_from": now - timedelta(days=1),
        "valid_until": now + timedelta(days=1),
    }
    assert eligible_memory(memory, "bank_a", 1, now=now)
    for field, value in [
        ("tenant_id", "bank_b"),
        ("scope", "production"),
        ("is_active", False),
        ("review_status", "UNVERIFIED"),
        ("clearance_level", 2),
        ("valid_from", now + timedelta(days=1)),
        ("valid_until", now),
    ]:
        assert not eligible_memory({**memory, field: value}, "bank_a", 1, now=now)


def test_snapshot_digest_survives_bson_millisecond_date_precision():
    moment = utcnow()
    persisted = moment.replace(microsecond=(moment.microsecond // 1000) * 1000)
    assert digest({"at": moment}) == digest({"at": persisted})
