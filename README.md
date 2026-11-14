# ChainLex

Project scaffold for a governed, auditable settlement-compliance agent. The approved architecture is in [the enriched hackathon plan](chainlex_enriched_hackathon_plan.md); the original [FireFly-inspired plan](firefly_fsm_chainlex_plan.md) remains available for context.

## Current capabilities

- Installable Python 3.12 package with separate API, worker, and simulator commands.
- Validated settings, tenant-bound demo authentication, typed workflow/action contracts, and connector protocol.
- API liveness/readiness, OpenAPI route contracts, and an explicit scaffold status page.
- Persistent MongoDB-backed simulator operations with idempotency and delayed verification.
- MongoDB collection/index bootstrap, replica-set preflight, and clearly labelled demo fixtures.
- Unit/HTTP tests, opt-in MongoDB integration tests, linting, package-build checks, and CI.

The worker is an idle scaffold, not an executing compliance agent. Workflow routes return **501 `WORKFLOW_NOT_IMPLEMENTED`** after authentication and validation. Regulatory retrieval, LLM analysis, policy execution, leases, outbox dispatch, governed-memory changes, and audit export are the next implementation phase. Simulator holds are fictional effects, never blockchain transactions.

## Quick start

Install [uv](https://docs.astral.sh/uv/) and Python 3.12, then run from the repository root:

```sh
uv sync --locked --group dev
cp .env.example .env
```

Set three distinct tokens in `.env`. Start the processes in separate terminals:

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

Without a reachable replica set this exits nonzero and reports a configuration/database error. With a reachable database it logs an idle scaffold cycle and exits successfully; it does not process jobs.

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
| `VOYAGE_API_KEY`, `EMBEDDING_MODEL`, `RERANK_MODEL` | Reserved retrieval configuration; no provider calls yet |
| `LLM_API_KEY`, `LLM_MODEL` | Reserved analyst configuration; no provider calls yet |
| `LEASE_SECONDS`, `HEARTBEAT_SECONDS`, `POLL_SECONDS` | Future worker timing; heartbeat must be shorter than lease |

Use only fictional demo data locally. This scaffold implements one server-configured demo tenant; multi-tenant authentication and production authorization remain part of the application work. There are no default usable tokens.

## Project map

```text
src/chainlex/
  api/          FastAPI app, authenticated route contracts, static status page
  domain/       Request/action models and permitted workflow transitions
  db/           Async MongoDB lifecycle, indexes, bootstrap, fixture seed
  connectors/   Settlement connector protocol and simulator HTTP adapter
  services/     Analyst, policy gate, fenced repository, and proposal interfaces
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
