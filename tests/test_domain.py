import pytest
from pydantic import ValidationError

from chainlex.config import Settings
from chainlex.domain.models import HoldAction, JobState
from chainlex.domain.transitions import can_transition


def test_terminal_jobs_cannot_restart():
    assert not can_transition(JobState.COMPLETED, JobState.CREATED)
    assert not can_transition(JobState.DENIED, JobState.READY)


def test_job_cannot_skip_policy():
    assert not can_transition(JobState.ANALYZING, JobState.DISPATCHING)
    assert can_transition(JobState.ANALYZING, JobState.AWAITING_POLICY)
    assert can_transition(JobState.AWAITING_POLICY, JobState.AWAITING_REVIEW)


@pytest.mark.parametrize("amount", [0, -1, 1.5, True])
def test_money_requires_positive_integer_minor_units(amount):
    with pytest.raises(ValidationError):
        HoldAction(tenant_id="tenant-a", settlement_id="s-1", amount_minor=amount)


def test_heartbeat_must_be_shorter_than_lease():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, lease_seconds=3, heartbeat_seconds=3)


def test_tokens_must_be_distinct():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, analyst_token="same", officer_token="same")
