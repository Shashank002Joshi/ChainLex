import sys

import pytest

from chainlex.db import cli
from chainlex.db.seed_reset import SeedResetError, validate_reset_target


@pytest.mark.parametrize(
    "database", ["chainlex_dev", "admin", "chainlex_manual_", "", "chainlex_manual_x/other"]
)
def test_reset_refuses_non_manual_namespace(database):
    with pytest.raises(SeedResetError):
        validate_reset_target(database, execute=False, confirmation=None)


def test_reset_preview_needs_no_confirmation():
    validate_reset_target("chainlex_manual_fsm", execute=False, confirmation=None)


@pytest.mark.parametrize("confirmation", [None, "chainlex_dev", "chainlex_manual_other"])
def test_execution_requires_exact_database_confirmation(confirmation):
    with pytest.raises(SeedResetError):
        validate_reset_target("chainlex_manual_fsm", execute=True, confirmation=confirmation)


def test_confirmation_without_execution_is_rejected():
    with pytest.raises(SeedResetError):
        validate_reset_target(
            "chainlex_manual_fsm", execute=False, confirmation="chainlex_manual_fsm"
        )


@pytest.mark.parametrize(
    "arguments",
    [
        ["seed-demo", "--reset"],
        ["bootstrap", "--reset", "--database", "chainlex_manual_fsm"],
        ["seed-demo", "--execute"],
        ["seed-demo", "--reset", "--database", "chainlex_dev"],
        ["seed-demo", "--reset", "--database", "chainlex_manual_fsm", "--execute"],
    ],
)
def test_cli_rejects_unsafe_reset_before_connecting(monkeypatch, arguments):
    monkeypatch.setattr(sys, "argv", ["chainlex-db", *arguments])
    monkeypatch.setattr(
        cli, "create_client", lambda *_: pytest.fail("Must reject before connecting")
    )
    with pytest.raises(SystemExit) as failure:
        cli.main()
    assert failure.value.code != 0
