"""Typed boundaries; request bodies cannot set authenticated tenant identity."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(min_length=1, max_length=128)]
MinorAmount = Annotated[int, Field(strict=True, gt=0)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class JobState(StrEnum):
    CREATED = "CREATED"
    ANALYZING = "ANALYZING"
    AWAITING_POLICY = "AWAITING_POLICY"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    READY = "READY"
    DISPATCHING = "DISPATCHING"
    CONFIRMING = "CONFIRMING"
    COMPLETED = "COMPLETED"
    DENIED = "DENIED"
    FAILED = "FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class Scenario(StrEnum):
    AUTOMATIC_HOLD = "automatic_hold"
    OFFICER_REVIEW = "officer_review"
    INVALIDATED_PRECEDENT = "invalidated_precedent"


class CreateJob(Contract):
    scenario: Scenario
    idempotency_key: Identifier


class ProposalDecision(Contract):
    decision: Literal["APPROVE", "REJECT"]
    proposal_version: Annotated[int, Field(strict=True, ge=1)]
    reason: Annotated[str, Field(min_length=1, max_length=2000)]


class ControlRequest(Contract):
    paused: Annotated[bool, Field(strict=True)]


class InvalidateMemory(Contract):
    reason: Annotated[str, Field(min_length=1, max_length=2000)]


class HoldAction(Contract):
    tenant_id: Identifier
    settlement_id: Identifier
    amount_minor: MinorAmount
    currency: Literal["USD"] = "USD"
    action_type: Literal["HOLD_SETTLEMENT"] = "HOLD_SETTLEMENT"


class PreparedAction(Contract):
    action: HoldAction
    idempotency_key: Identifier
    operation_id: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    payload_digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class DispatchReference(Contract):
    operation_id: str
    provider: Literal["simulator"] = "simulator"


class ProbeOutcome(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REVERTED = "REVERTED"
    UNKNOWN = "UNKNOWN"


class ProbeResult(Contract):
    operation_id: str
    outcome: ProbeOutcome
    settlement_id: str | None = None
    effect: Literal["HELD"] | None = None
