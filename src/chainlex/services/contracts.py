"""Analysis, authorization, and persistence boundaries for the future worker."""

from datetime import datetime
from typing import Literal, Protocol

from pydantic import AwareDatetime, Field

from chainlex.auth import Principal
from chainlex.domain.models import Contract, HoldAction, Identifier, JobState, PreparedAction


class EvidenceReference(Contract):
    document_id: Identifier
    version: int = Field(ge=1)
    text_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class Finding(Contract):
    verdict: Literal["EVIDENCE_SUPPORTED_RISK", "REVIEW_REQUIRED"]
    explanation: str = Field(min_length=1)
    evidence: tuple[EvidenceReference, ...] = ()
    precedent_ids: tuple[str, ...] = ()
    missing_facts: tuple[str, ...] = ()
    model: str
    prompt_version: str


class ActionProposal(Contract):
    proposal_id: Identifier
    job_id: Identifier
    tenant_id: Identifier
    version: int = Field(ge=1)
    action: HoldAction
    finding: Finding
    policy_version: int = Field(ge=1)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class Lease(Contract):
    worker_id: Identifier
    fencing_token: int = Field(ge=1)
    expires_at: AwareDatetime


class JobExecution(Contract):
    job_id: Identifier
    tenant_id: Identifier
    schema_version: Literal[1] = 1
    version: int = Field(ge=1)
    state: JobState = JobState.CREATED
    lease: Lease | None = None


class PolicyResult(Contract):
    outcome: Literal["APPROVE", "DENY", "REVIEW"]
    reason_codes: tuple[str, ...]
    policy_version: int = Field(ge=1)


class Analyst(Protocol):
    async def analyze(self, job: JobExecution) -> Finding: ...


class PolicyGate(Protocol):
    async def evaluate(self, proposal: ActionProposal, principal: Principal) -> PolicyResult: ...


class JobRepository(Protocol):
    async def claim(self, worker_id: str, now: datetime) -> JobExecution | None: ...

    async def transition(
        self, job: JobExecution, lease: Lease, next_state: JobState
    ) -> JobExecution: ...

    async def approve_and_enqueue(
        self, job: JobExecution, lease: Lease, proposal: ActionProposal, prepared: PreparedAction
    ) -> None:
        """Atomically persist approval, job transition, outbox action, and audit event."""
        ...
