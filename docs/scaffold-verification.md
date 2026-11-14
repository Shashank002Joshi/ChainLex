# Scaffold verification

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

Default offline test runs pass 30 tests and skip the explicitly opt-in MongoDB integration test. Starlette emits an upstream deprecation warning about its HTTPX-based test client; it does not affect the passing checks.

These checks establish the scaffold's boundaries and simulator persistence. They do not verify the planned compliance analysis, policy execution, job outbox, crash recovery, governed-memory decisions, hash-chain audit, external-provider integrations, or blockchain finality. Those features are not implemented by this scaffold.
