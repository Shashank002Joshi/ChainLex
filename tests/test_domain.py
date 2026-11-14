import pytest
from pydantic import ValidationError

from chainlex.config import Settings
from chainlex.domain.models import HoldAction


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
