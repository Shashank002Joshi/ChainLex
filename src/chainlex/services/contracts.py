"""Six-leg service and persistence interfaces; implementations remain separate."""

from datetime import datetime
from typing import Literal, Protocol, Self

from pydantic import AwareDatetime, Field, computed_field, model_validator

from chainlex.auth import Principal
from chainlex.domain.fsm import (
    SHARED_WAIT_STATES,
    STATE_DEFINITIONS,
    ArtifactReference,
    ComplianceEvent,
    ComplianceLeg,
    ComplianceState,
    EventType,
    WaitCheckpoint,
)
from chainlex.domain.models import Contract, CreateFSM, HoldAction, Identifier, PreparedAction
from chainlex.domain.transitions import TRANSITIONS


class EvidenceReference(Contract):
    document_id: Identifier
    version: int = Field(strict=True, ge=1)
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
    fsm_id: Identifier
    tenant_id: Identifier
    version: int = Field(strict=True, ge=1)
    action: HoldAction
    finding: Finding
    policy_version: int = Field(strict=True, ge=1)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def action_matches_tenant(self) -> Self:
        if self.action.tenant_id != self.tenant_id:
            raise ValueError("Proposal and action must belong to the same tenant")
        return self


class Lease(Contract):
    worker_id: Identifier
    fencing_token: int = Field(strict=True, ge=1)
    expires_at: AwareDatetime


class RuntimeMetadata(Contract):
    lease: Lease | None = None
    attempt: int = Field(default=0, strict=True, ge=0)
    next_attempt_at: AwareDatetime | None = None
    reconciliation_deadline: AwareDatetime | None = None


class ComplianceFSM(Contract):
    """Persist with exclude_computed_fields=True; leg and candidate events are inspection fields."""

    fsm_id: Identifier
    tenant_id: Identifier
    settlement_id: Identifier
    idempotency_key: Identifier
    previous_fsm_id: Identifier | None = None
    schema_version: Literal[1] = 1
    revision: int = Field(strict=True, ge=1)
    state: ComplianceState = ComplianceState.RECEIVED
    runtime: RuntimeMetadata = RuntimeMetadata()
    artifacts: tuple[ArtifactReference, ...] = ()
    last_event: ComplianceEvent | None = None
    wait: WaitCheckpoint | None = None
    blocking_reason_codes: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def checkpoints_match_state(self) -> Self:
        if self.state in SHARED_WAIT_STATES:
            expected = {"RETRY_WAIT": "retry", "AWAITING_INPUT": "input", "MANUAL_REVIEW": "manual"}
            if self.wait is None or self.wait.kind != expected[self.state]:
                raise ValueError("Shared wait state requires its matching persisted checkpoint")
        elif self.wait is not None:
            raise ValueError("Active/terminal state cannot retain a shared wait checkpoint")
        if self.state == ComplianceState.AWAITING_APPROVAL and not self.blocking_reason_codes:
            raise ValueError("Officer approval wait requires its reason codes")
        if self.last_event is not None and (
            self.last_event.fsm_id != self.fsm_id or self.last_event.tenant_id != self.tenant_id
        ):
            raise ValueError("Last event must belong to this FSM and tenant")
        return self

    @computed_field
    @property
    def leg(self) -> ComplianceLeg:
        state = self.wait.origin_state if self.state in SHARED_WAIT_STATES else self.state
        return STATE_DEFINITIONS[state].leg

    @computed_field
    @property
    def wait_reason(self) -> tuple[str, ...]:
        if self.wait:
            return self.wait.reason_codes
        return self.blocking_reason_codes if self.state == ComplianceState.AWAITING_APPROVAL else ()

    @computed_field
    @property
    def candidate_events(self) -> tuple[EventType, ...]:
        """Declared events only: guards, actor identity, and timers still require evaluation."""
        return tuple(rule.event for rule in TRANSITIONS if rule.from_state == self.state)


class PolicyResult(Contract):
    outcome: Literal["APPROVE", "DENY", "REVIEW"]
    reason_codes: tuple[str, ...]
    policy_version: int = Field(strict=True, ge=1)


class Analyst(Protocol):
    async def analyze(self, fsm: ComplianceFSM) -> Finding: ...


class PolicyGate(Protocol):
    async def evaluate(self, proposal: ActionProposal, principal: Principal) -> PolicyResult: ...


class ComplianceFSMRepository(Protocol):
    async def create_from_request(
        self, request: CreateFSM, event: ComplianceEvent
    ) -> ComplianceFSM:
        """Apply REQUEST_ACCEPTED with a unique tenant request key and initial audit event."""
        ...

    async def get(self, tenant_id: str, fsm_id: str) -> ComplianceFSM | None: ...

    async def claim(
        self, tenant_id: str, worker_id: str, now: datetime
    ) -> ComplianceFSM | None: ...

    async def apply_event(
        self, fsm: ComplianceFSM, event: ComplianceEvent, lease: Lease | None
    ) -> ComplianceFSM:
        """Atomically deduplicate, check guards, save artifacts/state, and append audit."""
        ...

    async def authorize_and_enqueue(
        self, fsm: ComplianceFSM, event: ComplianceEvent, proposal: ActionProposal, lease: Lease
    ) -> ComplianceFSM:
        """Apply POLICY_AUTHORIZED with a unique outbox intent in the same transaction."""
        ...

    async def grant_dispatch_permit(
        self,
        fsm: ComplianceFSM,
        event: ComplianceEvent,
        prepared: PreparedAction,
        lease: Lease,
        expected_control_revision: int,
    ) -> ComplianceFSM:
        """Apply SUBMISSION_PERMITTED and conditionally write the shared tenant control record."""
        ...
