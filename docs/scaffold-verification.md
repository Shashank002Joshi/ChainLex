# Scaffold verification

## Seed reset update

Verified on November 14, 2026: **68 tests passed**, including the Atlas reset integration test in a uniquely named disposable `chainlex_manual_verify_*` database. Test cleanup removed only that database.

- Normal seeding preserved edited fixtures and run records.
- The actual CLI preview reported deletion counts without modifying data.
- An injected restoration failure rolled back all runtime deletions.
- Reset refused a fixture ID occupied by a non-demo record.
- Confirmed CLI execution cleared the five runtime collections and restored the ten known fixtures.
- Indexes, validators, policies, controls, regulations, unrelated entity/case records, and an unknown collection were retained.
- Invalid/missing target and confirmation arguments were rejected before connection.
- Ruff checks, package build, CLI help, and whitespace checks passed.

No reset was executed against the user's application or manual-test namespace. The commands are documented in the manual-testing guide for deliberate use after services are stopped.

## Six-leg FSM interface update

Verified on November 14, 2026 after approval of the detailed FSM specification.

- The static contract defines six legs, 34 states, 50 event types, and 110 guarded transition descriptions. Tests follow the approved 25-event crash trace and check terminal, approval, retry, invalidation, and finalization boundaries.
- **52 tests passed**, including real MongoDB Atlas checks in a uniquely named disposable database. That database was dropped by test cleanup; application-data collections were not migrated.
- Atlas checks covered repeatable bootstrap, tenant-scoped FSM request uniqueness, audit event deduplication, simulator persistence, and preservation/rejection of legacy unique `job_id` indexes.
- A live API process passed Atlas readiness, authenticated `GET /api/fsms/definition`, and the 501 instance-creation boundary. HTTP tests rejected public state/event injection. The standalone worker passed `--once` and reported `fsm_scaffold_idle`.
- Ruff lint/format checks, package build, Compose configuration, and whitespace checks passed. `.env` remains ignored by Git.
- Default offline runs pass 51 tests and skip the explicitly opt-in MongoDB integration test.

The definition endpoint and pure checkpoint resolution do not execute authorization guards or persist transitions. Retrieval, policy handlers, the durable FSM repository, fenced worker processing, and full crash recovery through the FSM remain separate implementation work.

## Original scaffold snapshot

Verified on November 14, 2026 with Python 3.12.6 and a temporary MongoDB 8.0.16 single-node replica set bound to loopback. No Atlas, Voyage, or LLM credentials were used.

| Check | Result |
|---|---|
| `uv sync --locked --group dev` | Dependency environment installed from lockfile |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed |
| `uv run pytest` with `CHAINLEX_TEST_MONGODB_URI` | 31 passed, including real MongoDB integration |
| MongoDB bootstrap and fixture seeding | Repeatable; six entities and four inactive, unverified cases |
| Transaction preflight | Committed a transaction on the temporary replica set |
| Concurrent simulator dispatch | Eight requests persisted one operation |
| Conflicting idempotency key | Rejected without replacing the original effect |
| Live API and simulator processes | Liveness and database readiness returned 200 |
| Authenticated workflow request | Returned explicit 501, without claiming execution |
| Worker `--once` | Successful database startup check; reported idle scaffold |
| Simulator process restart | Previously dispatched operation remained confirmed; retry retained one operation |
| `docker compose config --quiet` | Passed; Docker daemon itself was not started |
| `uv build` | Wheel and source distribution built |
| Isolated installation of wheel | App and service contracts imported; static page and vector definitions present |
| Git hygiene | Local secrets, virtualenv, caches, and build outputs ignored |

At this original snapshot, offline runs passed 30 tests and skipped the explicitly opt-in MongoDB integration test. Starlette emits an upstream deprecation warning about its HTTPX-based test client; it does not affect the passing checks.

These checks establish the scaffold's boundaries and simulator persistence. They do not verify the planned compliance analysis, policy execution, job outbox, crash recovery, governed-memory decisions, hash-chain audit, external-provider integrations, or blockchain finality. Those features are not implemented by this scaffold.
