# ChainLex

Project scaffold for a governed, auditable settlement-compliance agent. The approved architecture is in [the enriched hackathon plan](chainlex_enriched_hackathon_plan.md); the original [FireFly-inspired plan](firefly_fsm_chainlex_plan.md) remains available for context.

## Current capabilities

- Installable Python 3.12 package with separate API, worker, and simulator commands.
- Validated settings, tenant-bound demo authentication, typed six-leg FSM/event/action contracts, and connector protocol.
- API liveness/readiness, OpenAPI route contracts, and an explicit scaffold status page.
- Persistent MongoDB-backed simulator operations with idempotency and delayed verification.
- EVM connector, chain indexer, event-bus, audit-pinning, and semantic-search modules with mocked-RPC tests; these are not yet wired into the compliance FSM worker.
- MongoDB collection/index bootstrap, replica-set preflight, and clearly labelled demo fixtures.
- Unit/HTTP tests, opt-in MongoDB integration tests, linting, package-build checks, and CI.

The worker is an idle scaffold, not an executing compliance agent. Workflow routes return **501 `WORKFLOW_NOT_IMPLEMENTED`** after authentication and validation. Regulatory retrieval, LLM analysis, policy execution, leases, outbox dispatch, governed-memory changes, and audit export are the next implementation phase. Simulator holds are fictional effects, never blockchain transactions.

## Quick start

For the complete manual walkthrough, expected HTTP responses, restart test, and MongoDB queries, see [Manual testing](docs/manual-testing.md). It uses a separate `chainlex_manual_fsm` database and distinguishes working simulator persistence from the FSM handlers that are still scaffolded.

Install [uv](https://docs.astral.sh/uv/) and Python 3.12, then run from the repository root:

```sh
uv sync --locked --group dev
cp -n .env.example .env
```

The copy command preserves an existing `.env`. Set three distinct tokens in `.env`. Start the processes in separate terminals:

```sh
uv run chainlex-api --port 8000
uv run chainlex-simulator --port 8001
uv run chainlex-worker
```

Open <http://127.0.0.1:8000/> for scaffold status and <http://127.0.0.1:8000/docs> for API contracts. Liveness works without credentials or a database. Readiness returns 503 until MongoDB is configured and reachable. The simulator requires its separate bearer token for operation requests.

For a bounded worker startup check:

```sh
uv run chainlex-worker --once
```

Without a reachable replica set this exits nonzero and reports a configuration/database error. With a reachable database it logs an idle scaffold cycle and exits successfully; it does not advance compliance FSMs.

## Inspect the six-leg FSM

The canonical sequence is **intake → evidence → analysis → authorization → dispatch → verification**. The full [FSM design](docs/superpowers/specs/2026-11-14-compliance-fsm-design.md) specifies guards, saved outputs, retries, and crash recovery for each substep.

With the API running, inspect its static definition without creating an FSM or sending a hold:

```sh
uv run python - <<'PYCODE'
import httpx
from chainlex.config import Settings
settings = Settings()
response = httpx.get(
    "http://127.0.0.1:8000/api/fsms/definition",
    headers={"Authorization": f"Bearer {settings.analyst_token.get_secret_value()}"},
)
response.raise_for_status()
contract = response.json()
for leg, states in contract["legs"].items():
    print(leg, "→".join(states))
print("SUBMITTING recovery:", contract["states"]["SUBMITTING"]["recovery"])
print("Runtime implemented:", contract["runtime_implemented"])
PYCODE
```

The response lists each transition's event, actor source, guards, and required writes. A declared edge is not authorization: `guards_evaluated` and `runtime_implemented` are both false. Shared waits derive their leg from a validated saved checkpoint; retries cannot resume an arbitrary submission.

The instance route contracts are now `POST /api/fsms`, `GET /api/fsms/{fsm_id}`, and its `/events` and `/export` subpaths. They return 501. The original `/api/jobs` scaffold routes have been replaced. Governance routes retain their existing roles.

New bootstrap definitions use `compliance_fsms`, `fsm_id` references, and `tenant_controls`. Existing `job_executions` records are not deleted or migrated. If old proposal/audit unique indexes reference `job_id`, bootstrap stops before changing collections; those indexes need a separately reviewed migration. Restart running services after updating the code.

## Local MongoDB

Start Docker Desktop first. The Compose file provides a loopback-only, development MongoDB replica set with persistent storage:

```sh
docker compose up -d mongo
docker compose exec mongo mongosh --quiet --eval 'rs.initiate({_id:"rs0",members:[{_id:0,host:"localhost:27017"}]})'
```

Initialize the replica set only once for its data volume. Wait until the node becomes primary, then set:

```dotenv
CHAINLEX_MONGODB_URI=mongodb://localhost:27017/?replicaSet=rs0&directConnection=true
CHAINLEX_DATABASE=chainlex_dev
```

Initialize the application collections and ordinary indexes:

```sh
uv run chainlex-db preflight
uv run chainlex-db bootstrap
uv run chainlex-db seed-demo
```

`preflight` checks replica-set/sharded topology and commits a disposable database transaction. `bootstrap` is repeatable. `seed-demo` creates six fictional entities and four unreviewed historical fixtures across two tenants without overwriting later edits. These fixtures are not eligible to authorize a compliance action.

For a clean manual rerun, stop the services and use the seed command's opt-in reset mode:

```sh
# Preview only
uv run chainlex-db seed-demo --reset --database chainlex_manual_fsm
# Execute after checking the preview
uv run chainlex-db seed-demo --reset --database chainlex_manual_fsm --execute --confirm-db chainlex_manual_fsm
```

Reset clears the five runtime collections and restores the ten known fixture records in one transaction. It preserves collections, indexes, unrelated entity/case records, regulations, policies, and controls. It is restricted to explicitly named `chainlex_manual_*` databases. See [manual reset and MongoDB checks](docs/manual-testing.md#9-optional-reset-through-the-seed-command) for details.

Plain local MongoDB does not provide the Atlas Vector Search service used by this project. Use Atlas for retrieval work; vector-index definitions live in `src/chainlex/db/vector_indexes.json`. No regulatory corpus or embeddings are fabricated by the scaffold.

The API, worker, and simulator run on the host by default. `Dockerfile` is also provided for packaging; a containerized process must use a MongoDB URI reachable from that container, not the host-only URI above.

## Configuration

All settings use the `CHAINLEX_` prefix; `.env` is local-only and ignored by Git.

| Setting | Purpose |
|---|---|
| `MONGODB_URI`, `DATABASE` | Operational database connection and namespace |
| `ANALYST_TOKEN`, `OFFICER_TOKEN` | Distinct bearer tokens for the configured demo tenant |
| `DEMO_TENANT_ID` | Server-owned tenant binding for both demo roles |
| `SIMULATOR_TOKEN`, `SIMULATOR_URL` | Separate connector credential and simulator endpoint |
| `VOYAGE_API_KEY`, `EMBEDDING_MODEL`, `RERANK_MODEL` | Shared Voyage embedding configuration; model fixed to `voyage-finance-2` for the 1024-dimensional indexes; reranking reserved |
| `LLM_API_KEY`, `LLM_MODEL` | Reserved analyst configuration; no provider calls yet |
| `LEASE_SECONDS`, `HEARTBEAT_SECONDS`, `POLL_SECONDS` | Future worker timing; heartbeat must be shorter than lease |
| `MAX_STEP_ATTEMPTS`, `RECONCILIATION_SECONDS` | Three attempts per step and a 120-second automated reconciliation deadline |

Use only fictional demo data locally. This scaffold implements one server-configured demo tenant; multi-tenant authentication and production authorization remain part of the application work. There are no default usable tokens.

## Project map

```text
src/chainlex/
  api/          FastAPI app, authenticated route contracts, static status page
  domain/       Six legs, state/event catalog, checkpoints, and transition contracts
  db/           Async MongoDB lifecycle, indexes, bootstrap, fixture seed
  connectors/   Settlement connector protocol and simulator HTTP adapter
  blockchain/   Chain indexing, decoded events, audit pinning, and transaction search
  services/     Analyst, policy gate, event-driven FSM repository, and proposal interfaces
  simulator/    Durable fictional settlement operations and HTTP service
  worker/       Independent idle worker entry point and shutdown handling
  auth.py       Server-bound demo identities and role checks
  config.py     Environment settings and startup validation
tests/          Offline tests and opt-in MongoDB integration tests
docs/           Scaffold implementation checklist
```

## Verification

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv build
```

The default tests need no external credentials and explicitly skip MongoDB integration tests. To run the persistence test against a disposable database, start the local replica set and use:

```sh
CHAINLEX_TEST_MONGODB_URI='mongodb://localhost:27017/?replicaSet=rs0&directConnection=true' uv run pytest -m integration -v
```

The integration test uses a unique database and drops only that database afterward. It verifies simulator idempotency, persistence across store instances, and conflicting-request rejection. The full crash-recovery and live Atlas/Voyage tests belong to the workflow implementation, not this scaffold.

## Next implementation steps

1. Add verified regulatory chunks, real Voyage embeddings/reranking, and a structured analyst result.
2. Implement tenant-scoped repositories, fenced leases, transactional proposals/outbox/audit, and policy enforcement.
3. Connect the worker to those services, then add recovery and governance acceptance tests.
4. Replace the status page with the operator dashboard and rehearse the three-minute demo.

See the enriched plan for the complete acceptance criteria and ordered roadmap.

Country corpus ingestion and retrieval are now available as standalone services;
see [country rules](docs/country-rules.md). Transactions, regulations and search
queries use the same async `VoyageEmbeddings` client in
`src/chainlex/services/embeddings.py`. Transaction/regulation text is embedded as
`document`, search text as `query`. These services are not wired into the idle
worker or scaffold workflow endpoints yet.
