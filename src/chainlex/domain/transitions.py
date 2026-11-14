"""Permitted transitions only; durable compare-and-swap is a separate service."""

from chainlex.domain.models import JobState

TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.CREATED: frozenset({JobState.ANALYZING, JobState.FAILED}),
    JobState.ANALYZING: frozenset(
        {JobState.AWAITING_POLICY, JobState.AWAITING_REVIEW, JobState.FAILED}
    ),
    JobState.AWAITING_POLICY: frozenset(
        {JobState.READY, JobState.AWAITING_REVIEW, JobState.DENIED, JobState.FAILED}
    ),
    JobState.AWAITING_REVIEW: frozenset(
        {JobState.ANALYZING, JobState.AWAITING_POLICY, JobState.DENIED}
    ),
    JobState.READY: frozenset(
        {JobState.DISPATCHING, JobState.AWAITING_POLICY, JobState.DENIED, JobState.FAILED}
    ),
    JobState.DISPATCHING: frozenset({JobState.CONFIRMING, JobState.MANUAL_REVIEW, JobState.FAILED}),
    JobState.CONFIRMING: frozenset({JobState.COMPLETED, JobState.MANUAL_REVIEW, JobState.FAILED}),
    JobState.MANUAL_REVIEW: frozenset({JobState.CONFIRMING, JobState.FAILED}),
    JobState.COMPLETED: frozenset(),
    JobState.DENIED: frozenset(),
    JobState.FAILED: frozenset(),
}


def can_transition(current: JobState, next_state: JobState) -> bool:
    return next_state in TRANSITIONS[current]
