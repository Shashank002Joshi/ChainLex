"""Six-leg state/event/checkpoint contracts; no durable runtime handlers live here."""

from enum import StrEnum
from types import MappingProxyType
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from chainlex.domain.models import Contract, Identifier


class ComplianceLeg(StrEnum):
    INTAKE = "intake"
    EVIDENCE = "evidence"
    ANALYSIS = "analysis"
    AUTHORIZATION = "authorization"
    DISPATCH = "dispatch"
    VERIFICATION = "verification"


class ComplianceState(StrEnum):
    RECEIVED = "RECEIVED"
    VALIDATING_CONTEXT = "VALIDATING_CONTEXT"
    RESOLVING_PARTIES = "RESOLVING_PARTIES"
    RESOLVING_JURISDICTIONS = "RESOLVING_JURISDICTIONS"
    CONTEXT_READY = "CONTEXT_READY"
    EMBEDDING_QUERY = "EMBEDDING_QUERY"
    SEARCHING_REGULATIONS = "SEARCHING_REGULATIONS"
    SEARCHING_PRECEDENTS = "SEARCHING_PRECEDENTS"
    RERANKING_EVIDENCE = "RERANKING_EVIDENCE"
    VALIDATING_EVIDENCE = "VALIDATING_EVIDENCE"
    EVIDENCE_READY = "EVIDENCE_READY"
    GENERATING_FINDING = "GENERATING_FINDING"
    VALIDATING_FINDING = "VALIDATING_FINDING"
    FINDING_READY = "FINDING_READY"
    EVALUATING_POLICY = "EVALUATING_POLICY"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    AUTHORIZED = "AUTHORIZED"
    PREPARING_ACTION = "PREPARING_ACTION"
    ACTION_PREPARED = "ACTION_PREPARED"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    SUBMISSION_UNKNOWN = "SUBMISSION_UNKNOWN"
    RECONCILING = "RECONCILING"
    AWAITING_EFFECT = "AWAITING_EFFECT"
    VERIFYING_EFFECT = "VERIFYING_EFFECT"
    EFFECT_CONFIRMED = "EFFECT_CONFIRMED"
    FINALIZING = "FINALIZING"
    FINALIZED = "FINALIZED"
    REJECTED = "REJECTED"
    DENIED = "DENIED"
    ACTION_FAILED = "ACTION_FAILED"
    RETRY_WAIT = "RETRY_WAIT"
    AWAITING_INPUT = "AWAITING_INPUT"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class EventSource(StrEnum):
    API = "api"
    WORKER = "worker"
    OFFICER = "officer"


class EventType(StrEnum):
    REQUEST_ACCEPTED = "REQUEST_ACCEPTED"
    START_INTAKE = "START_INTAKE"
    CONTEXT_VALIDATED = "CONTEXT_VALIDATED"
    PARTIES_RESOLVED = "PARTIES_RESOLVED"
    JURISDICTIONS_RESOLVED = "JURISDICTIONS_RESOLVED"
    INTAKE_REJECTED = "INTAKE_REJECTED"
    START_EVIDENCE = "START_EVIDENCE"
    QUERY_EMBEDDED = "QUERY_EMBEDDED"
    REGULATION_CANDIDATES_SAVED = "REGULATION_CANDIDATES_SAVED"
    PRECEDENT_CANDIDATES_SAVED = "PRECEDENT_CANDIDATES_SAVED"
    EVIDENCE_RERANKED = "EVIDENCE_RERANKED"
    EVIDENCE_VALIDATED = "EVIDENCE_VALIDATED"
    START_ANALYSIS = "START_ANALYSIS"
    FINDING_RETURNED = "FINDING_RETURNED"
    FINDING_VALIDATED = "FINDING_VALIDATED"
    START_POLICY_CHECK = "START_POLICY_CHECK"
    POLICY_AUTHORIZED = "POLICY_AUTHORIZED"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"
    OFFICER_APPROVED = "OFFICER_APPROVED"
    OFFICER_REJECTED = "OFFICER_REJECTED"
    POLICY_DENIED = "POLICY_DENIED"
    START_PREPARATION = "START_PREPARATION"
    ACTION_PREPARATION_SUCCEEDED = "ACTION_PREPARATION_SUCCEEDED"
    SUBMISSION_PERMITTED = "SUBMISSION_PERMITTED"
    CONNECTOR_ACCEPTED = "CONNECTOR_ACCEPTED"
    SUBMISSION_AMBIGUOUS = "SUBMISSION_AMBIGUOUS"
    START_RECONCILIATION = "START_RECONCILIATION"
    PROBE_PENDING = "PROBE_PENDING"
    PROBE_NOT_FOUND = "PROBE_NOT_FOUND"
    PROBE_UNKNOWN = "PROBE_UNKNOWN"
    PROBE_DUE = "PROBE_DUE"
    PROBE_CONFIRMED = "PROBE_CONFIRMED"
    ABSENCE_CONFIRMED = "ABSENCE_CONFIRMED"
    ACTION_FAILED = "ACTION_FAILED"
    EFFECT_MISMATCH = "EFFECT_MISMATCH"
    EFFECT_VERIFIED = "EFFECT_VERIFIED"
    START_FINALIZATION = "START_FINALIZATION"
    FINAL_RECORD_COMMITTED = "FINAL_RECORD_COMMITTED"
    TRANSIENT_FAILURE = "TRANSIENT_FAILURE"
    RETRY_DUE = "RETRY_DUE"
    INPUT_REQUIRED = "INPUT_REQUIRED"
    INPUT_CORRECTED = "INPUT_CORRECTED"
    EVIDENCE_STALE = "EVIDENCE_STALE"
    CONTEXT_STALE = "CONTEXT_STALE"
    AUTHORIZATION_STALE = "AUTHORIZATION_STALE"
    RECONCILIATION_EXPIRED = "RECONCILIATION_EXPIRED"
    OPERATOR_REQUIRED = "OPERATOR_REQUIRED"
    RECONCILIATION_REQUESTED = "RECONCILIATION_REQUESTED"
    FINALIZATION_BLOCKED = "FINALIZATION_BLOCKED"
    FINALIZATION_RETRY_REQUESTED = "FINALIZATION_RETRY_REQUESTED"


S = ComplianceState
TERMINAL_STATES = frozenset({S.REJECTED, S.DENIED, S.ACTION_FAILED, S.FINALIZED})
SHARED_WAIT_STATES = frozenset({S.RETRY_WAIT, S.AWAITING_INPUT, S.MANUAL_REVIEW})

LEG_STATES = MappingProxyType(
    {
        ComplianceLeg.INTAKE: (
            S.RECEIVED,
            S.VALIDATING_CONTEXT,
            S.RESOLVING_PARTIES,
            S.RESOLVING_JURISDICTIONS,
            S.CONTEXT_READY,
        ),
        ComplianceLeg.EVIDENCE: (
            S.EMBEDDING_QUERY,
            S.SEARCHING_REGULATIONS,
            S.SEARCHING_PRECEDENTS,
            S.RERANKING_EVIDENCE,
            S.VALIDATING_EVIDENCE,
            S.EVIDENCE_READY,
        ),
        ComplianceLeg.ANALYSIS: (S.GENERATING_FINDING, S.VALIDATING_FINDING, S.FINDING_READY),
        ComplianceLeg.AUTHORIZATION: (S.EVALUATING_POLICY, S.AWAITING_APPROVAL, S.AUTHORIZED),
        ComplianceLeg.DISPATCH: (
            S.PREPARING_ACTION,
            S.ACTION_PREPARED,
            S.SUBMITTING,
            S.SUBMITTED,
            S.SUBMISSION_UNKNOWN,
        ),
        ComplianceLeg.VERIFICATION: (
            S.RECONCILING,
            S.AWAITING_EFFECT,
            S.VERIFYING_EFFECT,
            S.EFFECT_CONFIRMED,
            S.FINALIZING,
            S.FINALIZED,
        ),
    }
)
_ORDER = {state: i for i, state in enumerate(s for states in LEG_STATES.values() for s in states)}
PRE_SUBMISSION_STATES = frozenset(state for state in _ORDER if _ORDER[state] < _ORDER[S.SUBMITTING])
SAFE_RETRY_STATES = frozenset(
    {
        S.RESOLVING_PARTIES,
        S.RESOLVING_JURISDICTIONS,
        S.EMBEDDING_QUERY,
        S.SEARCHING_REGULATIONS,
        S.SEARCHING_PRECEDENTS,
        S.RERANKING_EVIDENCE,
        S.VALIDATING_EVIDENCE,
        S.GENERATING_FINDING,
        S.VALIDATING_FINDING,
        S.EVALUATING_POLICY,
        S.PREPARING_ACTION,
        S.FINALIZING,
    }
)
INPUT_RESUME_STATES = frozenset(
    {
        S.VALIDATING_CONTEXT,
        S.RESOLVING_PARTIES,
        S.RESOLVING_JURISDICTIONS,
        S.EMBEDDING_QUERY,
        S.SEARCHING_REGULATIONS,
        S.SEARCHING_PRECEDENTS,
        S.RERANKING_EVIDENCE,
        S.VALIDATING_EVIDENCE,
        S.GENERATING_FINDING,
        S.EVALUATING_POLICY,
    }
)


class StateDefinition(Contract):
    leg: ComplianceLeg | None
    operation: str
    recovery: str
    safe_to_retry: bool = False


_OPERATIONS = {
    S.VALIDATING_CONTEXT: "validate_pending_settlement",
    S.RESOLVING_PARTIES: "resolve_exact_parties",
    S.RESOLVING_JURISDICTIONS: "resolve_sourced_jurisdictions",
    S.EMBEDDING_QUERY: "voyage_embed_saved_query",
    S.SEARCHING_REGULATIONS: "atlas_regulation_search",
    S.SEARCHING_PRECEDENTS: "atlas_governed_precedent_search",
    S.RERANKING_EVIDENCE: "voyage_rerank_candidates",
    S.VALIDATING_EVIDENCE: "validate_authoritative_evidence_versions",
    S.GENERATING_FINDING: "generate_untrusted_finding",
    S.VALIDATING_FINDING: "validate_saved_finding_and_citations",
    S.EVALUATING_POLICY: "evaluate_current_policy",
    S.AWAITING_APPROVAL: "wait_for_version_bound_officer_decision",
    S.PREPARING_ACTION: "prepare_side_effect_free_operation",
    S.ACTION_PREPARED: "obtain_serialized_dispatch_permit",
    S.SUBMITTING: "submit_saved_operation_once_per_permit",
    S.SUBMITTED: "schedule_probe",
    S.SUBMISSION_UNKNOWN: "schedule_probe",
    S.RECONCILING: "probe_saved_operation",
    S.AWAITING_EFFECT: "wait_for_probe_timer",
    S.VERIFYING_EFFECT: "validate_receipt_target_and_held_effect",
    S.EFFECT_CONFIRMED: "schedule_local_finalization",
    S.FINALIZING: "commit_audit_and_historical_case",
}
_LEGS = {state: leg for leg, states in LEG_STATES.items() for state in states}
_LEGS.update(
    {
        S.REJECTED: ComplianceLeg.INTAKE,
        S.DENIED: ComplianceLeg.AUTHORIZATION,
        S.ACTION_FAILED: ComplianceLeg.VERIFICATION,
    }
)


def _definition(state: ComplianceState) -> StateDefinition:
    recovery = "resume_saved_checkpoint"
    if state in TERMINAL_STATES:
        recovery = "terminal_no_resume"
    elif state in SHARED_WAIT_STATES:
        recovery = "resume_validated_wait_checkpoint"
    elif state in {S.SUBMITTING, S.SUBMITTED, S.SUBMISSION_UNKNOWN}:
        recovery = "probe_saved_operation"
    elif state in {S.EFFECT_CONFIRMED, S.FINALIZING}:
        recovery = "retry_local_finalization"
    return StateDefinition(
        leg=_LEGS.get(state),
        operation=(
            "terminal_no_work"
            if state in TERMINAL_STATES
            else _OPERATIONS.get(state, "await_next_guarded_event")
        ),
        recovery=recovery,
        safe_to_retry=state in SAFE_RETRY_STATES,
    )


STATE_DEFINITIONS = MappingProxyType({state: _definition(state) for state in ComplianceState})


class ArtifactReference(Contract):
    artifact_id: Identifier
    kind: Identifier
    version: int = Field(strict=True, ge=1)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class ComplianceEvent(Contract):
    event_id: Identifier
    fsm_id: Identifier
    tenant_id: Identifier
    event_type: EventType
    source: EventSource
    actor_id: Identifier
    expected_revision: int = Field(strict=True, ge=0)
    expected_state: ComplianceState | None
    occurred_at: AwareDatetime
    artifacts: tuple[ArtifactReference, ...] = ()


class WaitCheckpoint(Contract):
    kind: Literal["retry", "input", "manual"]
    origin_state: ComplianceState
    resume_state: ComplianceState
    reason_codes: tuple[Identifier, ...] = Field(min_length=1)
    input_revision: int = Field(strict=True, ge=1)
    input_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    attempt: int = Field(default=0, strict=True, ge=0)
    next_attempt_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_resume(self) -> Self:
        if self.kind == "retry":
            if self.next_attempt_at is None or self.attempt < 1:
                raise ValueError("Retry checkpoint requires its due time and consumed attempt")
            expected = (
                S.GENERATING_FINDING
                if self.origin_state == S.VALIDATING_FINDING
                else self.origin_state
            )
            if self.origin_state not in SAFE_RETRY_STATES or self.resume_state != expected:
                raise ValueError("Retry must resume the saved safe computation, never a submission")
        elif self.kind == "input":
            if (
                self.origin_state not in PRE_SUBMISSION_STATES
                or self.resume_state not in INPUT_RESUME_STATES
                or _ORDER[self.resume_state] > _ORDER[self.origin_state]
            ):
                raise ValueError("Input correction must resume the earliest affected prior state")
        else:
            allowed_origins = {
                S.SUBMITTING,
                S.SUBMITTED,
                S.SUBMISSION_UNKNOWN,
                S.RECONCILING,
                S.AWAITING_EFFECT,
                S.VERIFYING_EFFECT,
                S.EFFECT_CONFIRMED,
                S.FINALIZING,
            }
            expected = (
                S.FINALIZING
                if self.origin_state in {S.EFFECT_CONFIRMED, S.FINALIZING}
                else S.RECONCILING
            )
            if self.origin_state not in allowed_origins or self.resume_state != expected:
                raise ValueError(
                    "Manual recovery must reconcile or retry confirmed local finalization"
                )
        return self
