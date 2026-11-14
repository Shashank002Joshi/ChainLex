# ChainLex

A settlement-compliance scaffold built with Python 3.12, FastAPI, MongoDB Atlas,
and Voyage AI. Run commands from `./`.

## Current scope

- Six-leg FSM catalog: intake, evidence, analysis, authorization, dispatch, verification.
- Authenticated API contracts and a persistent settlement simulator.
- Regulation/policy seeding, governed retrieval services, and bank-route admission checks.
- EVM connector, chain indexer, event listener, audit pinning, and transaction embeddings.

The worker is idle and FSM instance/governance handlers return
`501 WORKFLOW_NOT_IMPLEMENTED`. Standalone services and simulator persistence do
not establish a working end-to-end compliance workflow.

## Setup

```sh
uv sync --locked --group dev
cp -n .env.example .env
```

Configure MongoDB and three distinct analyst/officer/simulator tokens in `.env`.
The copy preserves an existing file; `.env` is ignored by Git.

```sh
uv run chainlex-db preflight
uv run chainlex-db bootstrap
uv run chainlex-db seed-demo
```

Seeding retains six entity/four case fixtures and adds 12 review policies plus
three bank policies for the configured tenant. Regulations require real Voyage
embeddings; without a key, their phase reports `skipped`. Repeated seeds preserve
existing records and review decisions. New policies are inactive and UNVERIFIED;
regulation summaries need review and effective dates before governed retrieval.

Start each service in its own terminal:

```sh
uv run chainlex-api --port 8000
uv run chainlex-simulator --port 8001
```

Open <http://127.0.0.1:8000/> or the API documentation at
<http://127.0.0.1:8000/docs>. Simulator documentation is at
<http://127.0.0.1:8001/docs>. `uv run chainlex-worker --once` checks worker startup.

## Configuration

All variables have the `CHAINLEX_` prefix; see [`.env.example`](./.env.example).

| Variables | Purpose |
|---|---|
| `MONGODB_URI`, `DATABASE` | Database connection and namespace |
| `DEMO_TENANT_ID`, `ANALYST_TOKEN`, `OFFICER_TOKEN` | Server-bound demo identity and roles |
| `SIMULATOR_URL`, `SIMULATOR_TOKEN` | Simulator connection and separate credential |
| `VOYAGE_API_KEY`, `EMBEDDING_ENDPOINT` | Embedding provider; endpoint must match the key |
| `EMBEDDING_MODEL` | `voyage-finance-2`, 1,024 dimensions |
| `LEASE_SECONDS`, `HEARTBEAT_SECONDS`, `POLL_SECONDS` | Future worker timing |
| `MAX_STEP_ATTEMPTS`, `RECONCILIATION_SECONDS` | Retry and verification defaults |

The default embedding endpoint is `https://ai.mongodb.com/v1/embeddings` for Atlas
model keys. Voyage platform keys use `https://api.voyageai.com/v1/embeddings`.
LLM and reranking settings are reserved for the remaining workflow integration.

For local MongoDB, `./compose.yaml` provides a development replica set. Initialize
it once before running preflight. Atlas is required for the configured Vector
Search service; index definitions are in `./src/chainlex/db/vector_indexes.json`.

## Checks

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv build
```

Offline tests require no external credentials. Set `CHAINLEX_TEST_MONGODB_URI`
to run integration tests against uniquely named disposable databases.

## References

- [FSM states, events, guards, and recovery](./docs/fsm.md)
- [Country corpus, embedding, and bank policies](./docs/country-rules.md)
- [Settlement events and indexing](./docs/settlement-events.md)

## Presentation source material

- [Architecture, six-leg workflow, demo, and roadmap](./chainlex_enriched_hackathon_plan.md)
- [FireFly-inspired architecture and diagrams](./firefly_fsm_chainlex_plan.md)

These plans include proposed capabilities; use the current scope above when describing what the application executes today.
