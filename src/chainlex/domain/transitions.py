"""Declarative transition contracts, not authorization or durable state mutation."""

from types import MappingProxyType
from typing import Literal

from chainlex.domain.fsm import (
    PRE_SUBMISSION_STATES,
    SAFE_RETRY_STATES,
    STATE_DEFINITIONS,
    ComplianceLeg,
    ComplianceState,
    EventSource,
    EventType,
    WaitCheckpoint,
)
from chainlex.domain.models import Contract

S = ComplianceState
E = EventType


class TransitionDefinition(Contract):
    from_state: ComplianceState | None
    event: EventType
    destination: ComplianceState | None
    checkpoint_kind: Literal["retry", "input"] | None = None
    sources: tuple[EventSource, ...]
    guards: tuple[str, ...]
    writes: tuple[str, ...]


def _rule(
    source,
    event,
    destination,
    guards=(),
    writes=(),
    *,
    actor=EventSource.WORKER,
    checkpoint_kind=None,
):
    common = ("tenant_matches", "event_not_applied", "expected_state_and_revision")
    actor_guard = "worker_lease_and_fence" if actor == EventSource.WORKER else "server_bound_actor"
    return TransitionDefinition(
        from_state=source,
        event=event,
        destination=destination,
        checkpoint_kind=checkpoint_kind,
        sources=(actor,),
        guards=(*common, actor_guard, *guards),
        writes=("fsm_revision_and_state", "ordered_audit_event", *writes),
    )


_RULES = [
    _rule(
        None,
        E.REQUEST_ACCEPTED,
        S.RECEIVED,
        ("allowlisted_scenario", "tenant_request_key_unique"),
        ("original_request", "input_digest"),
        actor=EventSource.API,
    ),
    _rule(
        S.RECEIVED,
        E.START_INTAKE,
        S.VALIDATING_CONTEXT,
        ("request_snapshot_exists",),
        ("validation_attempt",),
    ),
    _rule(
        S.VALIDATING_CONTEXT,
        E.CONTEXT_VALIDATED,
        S.RESOLVING_PARTIES,
        ("positive_minor_units", "explicit_currency", "supported_pending_settlement"),
        ("normalized_transaction",),
    ),
    _rule(
        S.RESOLVING_PARTIES,
        E.PARTIES_RESOLVED,
        S.RESOLVING_JURISDICTIONS,
        ("exact_network_address_match", "party_source_versions_current"),
        ("resolved_parties",),
    ),
    _rule(
        S.RESOLVING_JURISDICTIONS,
        E.JURISDICTIONS_RESOLVED,
        S.CONTEXT_READY,
        ("jurisdictions_sourced",),
        ("context_snapshot", "context_digest"),
    ),
    _rule(
        S.CONTEXT_READY,
        E.START_EVIDENCE,
        S.EMBEDDING_QUERY,
        ("context_snapshot_current",),
        ("query_narrative", "query_digest", "embedding_model"),
    ),
    _rule(
        S.EMBEDDING_QUERY,
        E.QUERY_EMBEDDED,
        S.SEARCHING_REGULATIONS,
        ("embedding_valid_1024_dimensions", "query_digest_matches"),
        ("query_embedding",),
    ),
    _rule(
        S.SEARCHING_REGULATIONS,
        E.REGULATION_CANDIDATES_SAVED,
        S.SEARCHING_PRECEDENTS,
        ("governance_filters_applied",),
        ("regulation_candidates", "retrieval_scores"),
    ),
    _rule(
        S.SEARCHING_PRECEDENTS,
        E.PRECEDENT_CANDIDATES_SAVED,
        S.RERANKING_EVIDENCE,
        ("tenant_precedents_eligible",),
        ("precedent_candidates_or_empty_result",),
    ),
    _rule(
        S.RERANKING_EVIDENCE,
        E.EVIDENCE_RERANKED,
        S.VALIDATING_EVIDENCE,
        ("rerank_input_digest_matches",),
        ("ranked_clauses", "linked_applicability_and_exceptions"),
    ),
    _rule(
        S.VALIDATING_EVIDENCE,
        E.EVIDENCE_VALIDATED,
        S.EVIDENCE_READY,
        ("authoritative_versions_current", "scope_clearance_and_effective_dates_valid"),
        ("evidence_snapshot", "evidence_digest"),
    ),
    _rule(
        S.EVIDENCE_READY,
        E.START_ANALYSIS,
        S.GENERATING_FINDING,
        ("context_and_evidence_current",),
        ("analysis_input_manifest", "model_and_prompt_version"),
    ),
    _rule(
        S.GENERATING_FINDING,
        E.FINDING_RETURNED,
        S.VALIDATING_FINDING,
        ("analysis_input_digest_matches",),
        ("untrusted_candidate_finding",),
    ),
    _rule(
        S.VALIDATING_FINDING,
        E.FINDING_VALIDATED,
        S.FINDING_READY,
        ("finding_schema_valid", "citations_in_saved_evidence", "claims_supported"),
        ("validated_finding", "finding_digest"),
    ),
    _rule(
        S.FINDING_READY,
        E.START_POLICY_CHECK,
        S.EVALUATING_POLICY,
        ("finding_validated",),
        ("immutable_proposal", "proposal_digest_and_version"),
    ),
    _rule(
        S.EVALUATING_POLICY,
        E.POLICY_AUTHORIZED,
        S.AUTHORIZED,
        (
            "authority_valid",
            "tenant_target_action_allowed",
            "evidence_current",
            "finding_supports_action",
            "amount_within_limit_or_valid_officer_approval",
        ),
        ("authorization", "policy_version", "unique_pending_outbox_intent"),
    ),
    _rule(
        S.EVALUATING_POLICY,
        E.HUMAN_APPROVAL_REQUIRED,
        S.AWAITING_APPROVAL,
        ("otherwise_eligible", "automatic_limit_exceeded"),
        ("review_reason", "review_proposal_digest"),
    ),
    _rule(
        S.AWAITING_APPROVAL,
        E.OFFICER_APPROVED,
        S.EVALUATING_POLICY,
        ("officer_tenant_matches", "proposal_digest_and_version_match"),
        ("officer_decision",),
        actor=EventSource.OFFICER,
    ),
    _rule(
        S.AWAITING_APPROVAL,
        E.OFFICER_REJECTED,
        S.DENIED,
        ("officer_tenant_matches", "proposal_digest_and_version_match"),
        ("officer_rejection",),
        actor=EventSource.OFFICER,
    ),
    _rule(
        S.EVALUATING_POLICY,
        E.POLICY_DENIED,
        S.DENIED,
        ("deterministic_hard_denial",),
        ("denial_reason_codes",),
    ),
    _rule(
        S.AUTHORIZED,
        E.START_PREPARATION,
        S.PREPARING_ACTION,
        ("authorization_and_outbox_exist",),
        ("preparation_attempt",),
    ),
    _rule(
        S.PREPARING_ACTION,
        E.ACTION_PREPARATION_SUCCEEDED,
        S.ACTION_PREPARED,
        ("prepared_payload_matches_authorized_action",),
        ("prepared_operation", "operation_id", "idempotency_key", "payload_digest"),
    ),
    _rule(
        S.ACTION_PREPARED,
        E.SUBMISSION_PERMITTED,
        S.SUBMITTING,
        (
            "authorization_current",
            "prepared_operation_exists",
            "evidence_current",
            "tenant_control_revision_matches",
            "not_paused",
        ),
        ("dispatch_permit", "dispatch_attempt", "conditional_tenant_control_write"),
    ),
    _rule(
        S.SUBMITTING,
        E.CONNECTOR_ACCEPTED,
        S.SUBMITTED,
        ("response_matches_prepared_operation",),
        ("actual_connector_reference", "submission_response"),
    ),
    _rule(
        S.SUBMITTING,
        E.SUBMISSION_AMBIGUOUS,
        S.SUBMISSION_UNKNOWN,
        ("prepared_operation_exists",),
        ("ambiguous_error_class", "reconciliation_checkpoint"),
    ),
    _rule(
        S.RECONCILING,
        E.PROBE_CONFIRMED,
        S.VERIFYING_EFFECT,
        ("receipt_matches_prepared_operation",),
        ("confirmation_receipt",),
    ),
    _rule(S.AWAITING_EFFECT, E.PROBE_DUE, S.RECONCILING, ("probe_timer_due",), ("probe_attempt",)),
    _rule(
        S.RECONCILING,
        E.ABSENCE_CONFIRMED,
        S.ACTION_PREPARED,
        ("authoritative_absence", "same_prepared_operation", "authorization_current", "not_paused"),
        ("absence_evidence", "resubmission_reason"),
    ),
    _rule(
        S.VERIFYING_EFFECT,
        E.EFFECT_VERIFIED,
        S.EFFECT_CONFIRMED,
        ("receipt_succeeded", "tenant_target_operation_match", "held_effect_observed"),
        ("verification_evidence", "verification_digest"),
    ),
    _rule(
        S.EFFECT_CONFIRMED,
        E.START_FINALIZATION,
        S.FINALIZING,
        ("verified_effect_checkpoint_exists",),
        ("final_record_manifest",),
    ),
    _rule(
        S.FINALIZING,
        E.FINAL_RECORD_COMMITTED,
        S.FINALIZED,
        ("final_audit_and_case_commit_atomic",),
        ("final_audit_event", "unique_historical_case"),
    ),
    _rule(
        S.RETRY_WAIT,
        E.RETRY_DUE,
        None,
        ("retry_timer_due", "retry_budget_available", "saved_input_revision_matches"),
        ("retry_attempt",),
        checkpoint_kind="retry",
    ),
    _rule(
        S.AWAITING_INPUT,
        E.INPUT_CORRECTED,
        None,
        (
            "correction_authorized",
            "input_revision_changed",
            "earliest_affected_state",
            "no_unresolved_external_effect",
        ),
        ("new_input_revision", "invalidated_downstream_snapshots"),
        actor=EventSource.OFFICER,
        checkpoint_kind="input",
    ),
    _rule(
        S.MANUAL_REVIEW,
        E.RECONCILIATION_REQUESTED,
        S.RECONCILING,
        ("operator_authorized", "manual_checkpoint_requires_probe"),
        ("operator_reconcile_request",),
        actor=EventSource.OFFICER,
    ),
    _rule(
        S.MANUAL_REVIEW,
        E.FINALIZATION_RETRY_REQUESTED,
        S.FINALIZING,
        (
            "operator_authorized",
            "verified_effect_checkpoint_exists",
            "manual_checkpoint_is_finalization",
        ),
        ("operator_finalization_request",),
        actor=EventSource.OFFICER,
    ),
    _rule(
        S.FINALIZING,
        E.FINALIZATION_BLOCKED,
        S.MANUAL_REVIEW,
        ("verified_effect_checkpoint_exists",),
        ("manual_finalization_checkpoint",),
    ),
    _rule(
        S.VERIFYING_EFFECT,
        E.EFFECT_MISMATCH,
        S.MANUAL_REVIEW,
        ("receipt_or_effect_conflicts",),
        ("conflicting_evidence", "manual_checkpoint"),
    ),
]

for state in (S.VALIDATING_CONTEXT, S.RESOLVING_PARTIES, S.RESOLVING_JURISDICTIONS):
    _RULES.append(
        _rule(
            state,
            E.INTAKE_REJECTED,
            S.REJECTED,
            ("invalid_or_unsupported_context",),
            ("rejection_reason",),
        )
    )
for state in (S.SUBMITTING, S.SUBMITTED, S.SUBMISSION_UNKNOWN):
    _RULES.append(
        _rule(
            state,
            E.START_RECONCILIATION,
            S.RECONCILING,
            ("prepared_operation_exists",),
            ("probe_identity",),
        )
    )
for event in (E.PROBE_PENDING, E.PROBE_NOT_FOUND, E.PROBE_UNKNOWN):
    _RULES.append(
        _rule(
            S.RECONCILING,
            event,
            S.AWAITING_EFFECT,
            ("reconciliation_deadline_not_exhausted",),
            ("probe_result", "next_probe_at"),
        )
    )
for state in SAFE_RETRY_STATES:
    _RULES.append(
        _rule(
            state,
            E.TRANSIENT_FAILURE,
            S.RETRY_WAIT,
            ("safe_to_repeat", "retry_budget_available"),
            ("retry_checkpoint",),
        )
    )
for state in PRE_SUBMISSION_STATES:
    _RULES.append(
        _rule(
            state,
            E.INPUT_REQUIRED,
            S.AWAITING_INPUT,
            ("no_possible_external_effect",),
            ("input_wait_checkpoint",),
        )
    )
for state in (S.RECONCILING, S.AWAITING_EFFECT, S.VERIFYING_EFFECT):
    _RULES.append(
        _rule(
            state,
            E.RECONCILIATION_EXPIRED,
            S.MANUAL_REVIEW,
            ("deadline_exhausted",),
            ("unresolved_outcome", "manual_checkpoint"),
        )
    )
for state in (S.RECONCILING, S.VERIFYING_EFFECT):
    _RULES.append(
        _rule(
            state,
            E.ACTION_FAILED,
            S.ACTION_FAILED,
            ("authoritative_rejection", "hold_confirmed_absent"),
            ("failure_evidence",),
        )
    )
    _RULES.append(
        _rule(
            state,
            E.OPERATOR_REQUIRED,
            S.MANUAL_REVIEW,
            ("automated_resolution_unsafe",),
            ("manual_checkpoint",),
        )
    )
for state in (
    S.EVIDENCE_READY,
    S.GENERATING_FINDING,
    S.VALIDATING_FINDING,
    S.FINDING_READY,
    S.EVALUATING_POLICY,
    S.AWAITING_APPROVAL,
    S.AUTHORIZED,
    S.PREPARING_ACTION,
    S.ACTION_PREPARED,
):
    _RULES.append(
        _rule(
            state,
            E.EVIDENCE_STALE,
            S.EMBEDDING_QUERY,
            ("no_possible_external_effect", "upstream_context_current"),
            ("invalidated_evidence_and_analysis", "revoked_approval", "nondispatchable_intent"),
        )
    )
_RULES.append(
    _rule(
        S.ACTION_PREPARED,
        E.AUTHORIZATION_STALE,
        S.EVALUATING_POLICY,
        ("no_possible_external_effect", "evidence_current"),
        ("revoked_dispatch_permission",),
    )
)

_RULES.append(
    _rule(
        S.VERIFYING_EFFECT,
        E.PROBE_UNKNOWN,
        S.AWAITING_EFFECT,
        ("reconciliation_deadline_not_exhausted", "prepared_operation_exists"),
        ("effect_read_unavailable", "next_probe_at"),
    )
)
for state in PRE_SUBMISSION_STATES:
    if STATE_DEFINITIONS[state].leg != ComplianceLeg.INTAKE or state == S.CONTEXT_READY:
        _RULES.append(
            _rule(
                state,
                E.CONTEXT_STALE,
                S.VALIDATING_CONTEXT,
                ("no_possible_external_effect", "changed_context_source_version"),
                (
                    "invalidated_context_and_downstream_artifacts",
                    "revoked_approval",
                    "nondispatchable_intent",
                ),
            )
        )

TRANSITIONS = tuple(sorted(_RULES, key=lambda rule: (rule.from_state or "", rule.event)))
_BY_EVENT = MappingProxyType({(rule.from_state, rule.event): rule for rule in TRANSITIONS})
if len(_BY_EVENT) != len(TRANSITIONS):
    raise RuntimeError("Duplicate state/event transition definition")


def transition_for(state: ComplianceState | None, event: EventType) -> TransitionDefinition | None:
    """Return a declared edge. The presence of an edge does not mean its guards passed."""
    return _BY_EVENT.get((state, event))


def resolve_destination(rule: TransitionDefinition, checkpoint: WaitCheckpoint | None = None):
    """Resolve saved wait metadata only; never authorizes or applies a transition."""
    if rule.checkpoint_kind is not None:
        if checkpoint is None or checkpoint.kind != rule.checkpoint_kind:
            raise ValueError("Transition requires its persisted wait checkpoint")
        return checkpoint.resume_state
    if rule.from_state == S.MANUAL_REVIEW:
        if checkpoint is None or checkpoint.kind != "manual":
            raise ValueError("Manual recovery requires a persisted manual checkpoint")
        if checkpoint.resume_state != rule.destination:
            raise ValueError(
                "Manual recovery cannot skip the saved verification/finalization boundary"
            )
    return rule.destination
