"""Typed audit workflow boundaries. Identities and tenant claims are server assigned."""

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import AwareDatetime, Field, field_validator

from chainlex.domain.models import Contract, Identifier


def utcnow() -> datetime:
    return datetime.now(UTC)


def digest(value: Any) -> str:
    def canonical_default(item):
        if isinstance(item, datetime):
            # BSON dates retain milliseconds. Hash the same representation before
            # and after persistence, including caller-supplied aware timestamps.
            return item.astimezone(UTC).isoformat(timespec="milliseconds")
        return str(item)

    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=canonical_default).encode()
    ).hexdigest()


class AgentId(StrEnum):
    ACTION = "auditable_action"
    MEMORY = "governed_memory"
    COMPLETION = "durable_completion"


class AuditState(StrEnum):
    RECEIVED = "RECEIVED"
    EVIDENCE = "RETRIEVING_EVIDENCE"
    ANALYSIS = "ASSESSING_ROUTES"
    DRAFT = "PUBLISHING_DRAFT"
    REVIEW = "AWAITING_HUMAN_REVIEW"
    FINAL = "PUBLISHING_FINAL"
    FINALIZED = "FINALIZED"
    RETRY = "RETRY_WAIT"
    MANUAL = "MANUAL_REVIEW"


ACTIVE_STATES = (
    AuditState.RECEIVED,
    AuditState.EVIDENCE,
    AuditState.ANALYSIS,
    AuditState.DRAFT,
    AuditState.FINAL,
)


class CreateAudit(Contract):
    scenario: Literal[
        "corridor_audit",
        "memory_influence",
        "no_suitable_route",
        "schema_change",
        "unsupported_schema",
    ] = "corridor_audit"
    idempotency_key: Identifier
    previous_audit_id: Identifier | None = None


class HumanGate(Contract):
    gate_id: Identifier
    title: str
    reason: str
    required: bool = True
    status: Literal["PENDING", "APPROVED", "REJECTED"] = "PENDING"
    decision_reason: str | None = None
    actor_id: str | None = None
    decided_at: AwareDatetime | None = None


class GateDecision(Contract):
    decision: Literal["APPROVE", "REJECT"]
    analysis_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_revision: int = Field(strict=True, ge=1)
    reason: str = Field(min_length=1, max_length=2000)


class MemoryCreate(Contract):
    narrative: str = Field(min_length=10, max_length=8000)
    route_id: Identifier
    required_gate: str = Field(min_length=1, max_length=1000)
    clearance_level: int = Field(default=1, strict=True, ge=1, le=2)
    valid_until: AwareDatetime

    @field_validator("valid_until")
    @classmethod
    def future_expiry(cls, value):
        if value <= utcnow():
            raise ValueError("Memory expiry must be in the future")
        return value


class MemoryCorrection(MemoryCreate):
    expected_version: int = Field(strict=True, ge=1)
    reason: str = Field(min_length=1, max_length=2000)


class MemoryInvalidation(Contract):
    expected_version: int = Field(strict=True, ge=1)
    reason: str = Field(min_length=1, max_length=2000)


class PolicyChange(Contract):
    expected_version: int = Field(strict=True, ge=1)
    reason: str = Field(min_length=1, max_length=2000)
    blocked_route_ids: tuple[Identifier, ...] = ()


class PolicyChangeDecision(Contract):
    decision: Literal["APPROVE", "REJECT"]
    expected_version: int = Field(strict=True, ge=1)
    reason: str = Field(min_length=1, max_length=2000)


class RetryAudit(Contract):
    expected_revision: int = Field(strict=True, ge=1)
    reason: str = Field(min_length=1, max_length=2000)


class AgentControl(Contract):
    is_active: bool = Field(strict=True)
    reason: str = Field(min_length=1, max_length=2000)


class AuditRun(Contract):
    audit_id: Identifier
    fsm_id: Identifier
    tenant_id: Identifier
    schema_version: Literal[2] = 2
    workflow_type: Literal["AUDIT"] = "AUDIT"
    mode: Literal["scripted_demo"] = "scripted_demo"
    scenario: str
    idempotency_key: Identifier
    previous_audit_id: Identifier | None = None
    initiated_by: str
    clearance_level: int = 1
    revision: int = 1
    state: AuditState = AuditState.RECEIVED
    checkpoint: dict = Field(default_factory=dict)
    gates: tuple[HumanGate, ...] = ()
    analysis_digest: str | None = None
    governance_revision: int | None = None
    lease_owner: str | None = None
    lease_expires_at: AwareDatetime | None = None
    fencing_token: int = 0
    attempts: int = 0
    next_attempt_at: AwareDatetime | None = None
    resume_state: AuditState | None = None
    error_code: str | None = None
    last_event_hash: str = "0" * 64
    created_at: AwareDatetime = Field(default_factory=utcnow)
    updated_at: AwareDatetime = Field(default_factory=utcnow)

    @property
    def leg(self):
        state = (
            self.resume_state if self.state in {AuditState.RETRY, AuditState.MANUAL} else self.state
        )
        return {
            AuditState.RECEIVED: "intake",
            AuditState.EVIDENCE: "evidence",
            AuditState.ANALYSIS: "analysis",
            AuditState.DRAFT: "draft",
            AuditState.REVIEW: "human_review",
            AuditState.FINAL: "finalization",
            AuditState.FINALIZED: "finalization",
        }.get(state, "manual_review")


class AuditConflict(ValueError):
    """A stale revision, lease, policy or decision cannot authorize a mutation."""


class AuditNotFound(ValueError):
    """No resource exists within the authenticated tenant's scope."""


class ActionDenied(ValueError):
    """Deterministic policy refused an action before invoking its tool."""


class WorkflowPaused(ValueError):
    """No new work permit is available while a tenant is paused."""


class UnsupportedSchema(ValueError):
    """No reviewed adapter exists for this input schema."""


class EmbeddingUnavailable(RuntimeError):
    """A real embedding provider is required; synthetic vectors are not substituted."""
