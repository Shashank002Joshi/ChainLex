# Seed Demo Reset Implementation Plan

> **For agentic workers:** Execute inline using the existing writing/executing-plans workflow. The user requested reset behavior on the seed command instead of a separate cleanup command.

**Goal:** Add a preview-first `seed-demo --reset` mode for repeatable manual testing.

**Architecture:** Normal seeding remains idempotent. Reset mode requires an explicit `chainlex_manual_*` namespace; execution additionally requires `--execute --confirm-db NAME`. In one transaction, clear the five runtime collections and restore only the ten known demo fixture IDs. Keep collections, indexes, unrelated entity/case records, regulations, policies, controls, and unknown collections.

**Tech Stack:** Existing Python CLI, async PyMongo transactions, pytest.

## Task 1: Guard and CLI tests

Files: `tests/test_seed_reset.py`, `src/chainlex/db/cli.py`, `src/chainlex/db/seed_reset.py`.

- [x] Test refusal of non-manual namespaces, missing explicit database, mismatched confirmation, and reset flags on unrelated commands before any connection.
- [x] Verify normal `seed-demo` and preview mode cannot invoke deletion.
- [x] Run `uv run pytest tests/test_seed_reset.py` before implementation; expect missing reset module.

```python
with pytest.raises(SeedResetError):
    validate_reset_target("chainlex_dev", execute=True, confirmation="chainlex_dev")
```

## Task 2: Extract fixtures and implement reset

Files: `src/chainlex/db/seeding.py`, `src/chainlex/db/seed_reset.py`, `src/chainlex/db/cli.py`.

- [x] Extract the existing fixture generator/seeder without changing ordinary upsert behavior.
- [x] Preview counts for the runtime collections and fixture IDs; reject missing bootstrap or fixture-ID collisions with non-demo records.
- [x] On confirmed execution, clear runtime records and replace known fixture documents in one transaction. Propagate failures so the transaction aborts.
- [x] Report actual deletion/restoration counts without credentials.

Runtime collections: `compliance_fsms`, `agent_action_proposals`, `tx_outbox`, `audit_ledger`, `simulator_operations`.

## Task 3: Verification and documentation

Files: `tests/test_seed_reset_integration.py`, `README.md`, `docs/manual-testing.md`.

- [x] Verify preview, ordinary-seed preservation, atomic rollback, protected fixtures, successful reset, retained indexes, and unrelated-record preservation against a disposable Atlas database.
- [x] Document preview and explicit execution, required service shutdown, retained data, and MongoDB checks after reset.
- [x] Run lint/format, tests, build, and CLI help; preserve existing workspace changes and `.env`.

```sh
uv run chainlex-db seed-demo --reset --database chainlex_manual_fsm
uv run chainlex-db seed-demo --reset --database chainlex_manual_fsm --execute --confirm-db chainlex_manual_fsm
```

Only tests execute reset against a uniquely named disposable database. Creating this feature does not clear the user's manual/application database.
