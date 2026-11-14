import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from chainlex.domain.fsm import (
    STATE_DEFINITIONS,
    TERMINAL_STATES,
    ComplianceEvent,
    ComplianceLeg,
    ComplianceState,
    EventSource,
    EventType,
    WaitCheckpoint,
)
from chainlex.domain.transitions import TRANSITIONS, resolve_destination, transition_for
from chainlex.services.contracts import ComplianceFSM


def make_wait(**kwargs):
    values = {
        "input_digest": "a" * 64,
        "next_attempt_at": datetime.now(UTC),
        "attempt": 1,
    }
    return WaitCheckpoint(**(values | kwargs))


def test_approved_crash_trace_is_representable_without_skipping_legs():
    spec = Path("docs/superpowers/specs/2026-11-14-compliance-fsm-design.md").read_text()
    trace = re.findall(r"^([A-Z_]+)\s*->\s*([A-Z_]+)$", spec, re.M)
    assert len(trace) == 25
    current = None
    seen_legs = set()
    for event, expected in trace:
        rule = transition_for(current, EventType(event))
        assert rule is not None, (current, event)
        assert rule.destination == ComplianceState(expected)
        current = rule.destination
        seen_legs.add(STATE_DEFINITIONS[current].leg)
    assert current == ComplianceState.FINALIZED
    assert seen_legs == set(ComplianceLeg)


def test_every_state_has_recovery_metadata_and_terminals_have_no_exits():
    assert set(STATE_DEFINITIONS) == set(ComplianceState)
    assert len({(rule.from_state, rule.event) for rule in TRANSITIONS}) == len(TRANSITIONS)
    assert {rule.event for rule in TRANSITIONS} == set(EventType)
    for state, definition in STATE_DEFINITIONS.items():
        assert definition.operation and definition.recovery
        if state in TERMINAL_STATES:
            assert definition.operation == "terminal_no_work"
            assert not any(rule.from_state == state for rule in TRANSITIONS)


def test_submission_crash_probes_and_cannot_use_transient_resend():
    rule = transition_for(ComplianceState.SUBMITTING, EventType.START_RECONCILIATION)
    assert rule.destination == ComplianceState.RECONCILING
    assert "prepared_operation_exists" in rule.guards
    assert transition_for(ComplianceState.SUBMITTING, EventType.TRANSIENT_FAILURE) is None
    definition = STATE_DEFINITIONS[ComplianceState.SUBMITTING]
    assert definition.recovery == "probe_saved_operation"


def test_not_found_does_not_authorize_a_new_submission():
    rule = transition_for(ComplianceState.RECONCILING, EventType.PROBE_NOT_FOUND)
    assert rule.destination == ComplianceState.AWAITING_EFFECT
    absent = transition_for(ComplianceState.RECONCILING, EventType.ABSENCE_CONFIRMED)
    assert absent.destination == ComplianceState.ACTION_PREPARED
    assert {"authoritative_absence", "same_prepared_operation", "authorization_current"} <= set(
        absent.guards
    )


def test_officer_approval_always_reenters_policy():
    rule = transition_for(ComplianceState.AWAITING_APPROVAL, EventType.OFFICER_APPROVED)
    assert rule.destination == ComplianceState.EVALUATING_POLICY
    assert rule.sources == (EventSource.OFFICER,)
    assert "proposal_digest_and_version_match" in rule.guards
    assert transition_for(ComplianceState.GENERATING_FINDING, EventType.POLICY_AUTHORIZED) is None


def test_dispatch_permit_declares_governance_serialization():
    rule = transition_for(ComplianceState.ACTION_PREPARED, EventType.SUBMISSION_PERMITTED)
    assert {"tenant_control_revision_matches", "authorization_current", "not_paused"} <= set(
        rule.guards
    )
    assert "dispatch_permit" in rule.writes


def test_retry_checkpoint_cannot_resume_a_submission():
    with pytest.raises(ValidationError):
        make_wait(
            kind="retry",
            origin_state="SUBMITTING",
            resume_state="SUBMITTING",
            reason_codes=("TIMEOUT",),
            input_revision=1,
        )


def test_retry_resumes_exact_saved_computation():
    checkpoint = make_wait(
        kind="retry",
        origin_state="SEARCHING_PRECEDENTS",
        resume_state="SEARCHING_PRECEDENTS",
        reason_codes=("TRANSIENT_PROVIDER_ERROR",),
        input_revision=1,
    )
    rule = transition_for(ComplianceState.RETRY_WAIT, EventType.RETRY_DUE)
    assert resolve_destination(rule, checkpoint) == ComplianceState.SEARCHING_PRECEDENTS
    with pytest.raises(ValueError):
        resolve_destination(rule, None)


def test_input_correction_cannot_jump_forward_to_policy_or_dispatch():
    for destination in ("EVALUATING_POLICY", "ACTION_PREPARED", "SUBMITTING"):
        with pytest.raises(ValidationError):
            make_wait(
                kind="input",
                origin_state="VALIDATING_CONTEXT",
                resume_state=destination,
                reason_codes=("MISSING_FACTS",),
                input_revision=1,
            )


def test_wait_leg_is_derived_from_checkpoint_not_writable():
    checkpoint = make_wait(
        kind="retry",
        origin_state="SEARCHING_PRECEDENTS",
        resume_state="SEARCHING_PRECEDENTS",
        reason_codes=("RATE_LIMIT",),
        input_revision=1,
    )
    fsm = ComplianceFSM(
        fsm_id="fsm-1",
        tenant_id="bank_a",
        settlement_id="settlement-1",
        idempotency_key="request-1",
        revision=1,
        state="RETRY_WAIT",
        wait=checkpoint,
    )
    assert fsm.leg == ComplianceLeg.EVIDENCE
    assert fsm.wait_reason == ("RATE_LIMIT",)
    with pytest.raises(ValidationError):
        ComplianceFSM(**(fsm.model_dump(exclude_computed_fields=True) | {"leg": "dispatch"}))


def test_wait_states_require_matching_checkpoint():
    with pytest.raises(ValidationError):
        ComplianceFSM(
            fsm_id="fsm-1",
            tenant_id="bank_a",
            settlement_id="settlement-1",
            idempotency_key="request-1",
            revision=1,
            state="RETRY_WAIT",
        )


def test_officer_approval_wait_exposes_reason_and_authorization_leg():
    fsm = ComplianceFSM(
        fsm_id="fsm-1",
        tenant_id="bank_a",
        settlement_id="s-1",
        idempotency_key="request-1",
        revision=1,
        state="AWAITING_APPROVAL",
        blocking_reason_codes=("AUTOMATIC_LIMIT_EXCEEDED",),
    )
    assert fsm.leg == ComplianceLeg.AUTHORIZATION
    assert fsm.wait_reason == ("AUTOMATIC_LIMIT_EXCEEDED",)
    with pytest.raises(ValidationError):
        ComplianceFSM(
            **(fsm.model_dump(exclude_computed_fields=True) | {"blocking_reason_codes": ()})
        )


def test_finalization_recovery_cannot_resend_or_reprobe():
    definition = STATE_DEFINITIONS[ComplianceState.FINALIZING]
    assert definition.recovery == "retry_local_finalization"
    assert transition_for(ComplianceState.FINALIZING, EventType.START_PREPARATION) is None
    checkpoint = make_wait(
        kind="manual",
        origin_state="FINALIZING",
        resume_state="FINALIZING",
        reason_codes=("AUDIT_WRITE_FAILED",),
        input_revision=1,
    )
    rule = transition_for(ComplianceState.MANUAL_REVIEW, EventType.FINALIZATION_RETRY_REQUESTED)
    assert resolve_destination(rule, checkpoint) == ComplianceState.FINALIZING
    with pytest.raises(ValueError):
        resolve_destination(
            transition_for(ComplianceState.MANUAL_REVIEW, EventType.RECONCILIATION_REQUESTED),
            checkpoint,
        )


def test_event_identity_and_revision_cannot_be_omitted_or_model_authored():
    with pytest.raises(ValidationError):
        ComplianceEvent(
            event_id="e-1",
            fsm_id="fsm-1",
            tenant_id="bank_a",
            event_type="OFFICER_APPROVED",
            source="llm",
            actor_id="model",
            expected_revision=1,
            expected_state="AWAITING_APPROVAL",
            occurred_at=datetime.now(UTC),
        )


def test_retry_requires_persisted_due_time_and_input_digest():
    with pytest.raises(ValidationError):
        WaitCheckpoint(
            kind="retry",
            origin_state="SEARCHING_PRECEDENTS",
            resume_state="SEARCHING_PRECEDENTS",
            reason_codes=("RATE_LIMIT",),
            input_revision=1,
        )


def test_context_invalidation_returns_to_intake_only_before_possible_send():
    rule = transition_for(ComplianceState.ACTION_PREPARED, EventType.CONTEXT_STALE)
    assert rule.destination == ComplianceState.VALIDATING_CONTEXT
    assert "nondispatchable_intent" in rule.writes
    assert transition_for(ComplianceState.SUBMITTING, EventType.CONTEXT_STALE) is None


def test_unavailable_effect_read_can_wait_or_expire_without_resending():
    rule = transition_for(ComplianceState.VERIFYING_EFFECT, EventType.PROBE_UNKNOWN)
    assert rule.destination == ComplianceState.AWAITING_EFFECT
    expired = transition_for(ComplianceState.VERIFYING_EFFECT, EventType.RECONCILIATION_EXPIRED)
    assert expired.destination == ComplianceState.MANUAL_REVIEW
