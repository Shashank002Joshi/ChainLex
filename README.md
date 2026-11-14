# ChainLex

A settlement-compliance project built with Python 3.12, FastAPI, MongoDB Atlas,
and Voyage AI. Run commands from `./`.

## Current scope

- Three working audit agents: Auditable Action, Governed Memory, and Durable Completion.
- Durable audit FSM, officer review gates, versioned PDF reports, and JSON audit export.
- Tenant/clearance/expiry-scoped memory, corrections, invalidation, and behavioral comparisons.
- Identity-bound action permits, officer-approved policy changes, pause, and crash recovery.
- Separate settlement FSM catalog: intake, evidence, analysis, authorization, dispatch, verification.
- Authenticated API contracts and a persistent settlement simulator.
- Regulation/policy seeding, governed retrieval services, and bank-route admission checks.
- EVM connector, chain indexer, event listener, audit pinning, and transaction embeddings.

Audit reasoning and corridor discovery use labelled scripted fixtures. Voyage
embeddings, Atlas persistence/Vector Search, human gates, and PDF publication are
real. Human analyst/officer permissions remain separate from agent identities.
Audit operations do not move funds. Settlement FSM instance/proposal routes still
return `501 WORKFLOW_NOT_IMPLEMENTED`; standalone EVM modules remain separate.

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
uv run chainlex-db audit-indexes
uv run chainlex-db seed-audit-demo
```

Seeding retains six entity/four case fixtures and adds 12 review policies plus
three bank policies for the configured tenant. Regulations require real Voyage
embeddings; without a key, their phase reports `skipped`. Repeated seeds preserve
existing records and review decisions. New policies are inactive and UNVERIFIED;
regulation summaries need review and effective dates before governed retrieval.
`audit-indexes` provisions the audit memory/regulation Vector Search indexes;
rerun it until both are queryable. `seed-audit-demo` independently adds tenant-owned
agent identities, versioned demo policy, five scenarios, and a real embedded demo
precedent. It preserves existing memory corrections and invalidations.

Start each service in its own terminal:

```sh
uv run chainlex-api --port 8000
uv run chainlex-worker
```

Open <http://127.0.0.1:8000/> or the API documentation at
<http://127.0.0.1:8000/docs>. Use **Authorize** with the configured analyst or
officer bearer token. `uv run chainlex-worker --once` checks startup only;
`--drain` processes currently ready steps and exits at human/timer waits.
The separate settlement simulator starts with `uv run chainlex-simulator --port 8001`.

## Operator workspace

Open the API root to inspect the three agent outputs, suggested corridors, human
gates, activity, and draft/final PDFs. The initial **Preview workspace** uses
clearly labeled sample data. **Connect workspace** accepts the backend access
and optional officer tokens; credentials stay in the current tab's memory.
Start an audit or open an audit ID. Connected activity polls the audit ledger
every two seconds; it is distinct from the fixed sample timeline.

**Create transaction** represents an upstream settlement request. It needs no
wallet integration. Configure these server-only values in `.env`:

```sh
CHAINLEX_SEPOLIA_PRIVATE_KEY=
CHAINLEX_SEPOLIA_RPC_URL=https://ethereum-sepolia-rpc.publicnode.com
CHAINLEX_SEPOLIA_CONTRACT_ADDRESS=
```

Only an officer may submit a transaction. The server checks the Sepolia chain,
saves the signed bytes and transaction hash before broadcast, and checks the
receipt and settlement event before showing confirmation. The request records
asset metadata; it does not transfer USDC. A confirmed request can create a
linked demo audit containing the actual amount, route, and transaction reference.
The audit's compliance reasoning and bank relationships remain scripted demo data.

**Run preflight** uses the latest `/api/compliance/verify` endpoint in simulated
mode and displays the three court submissions and completed six-leg trace.
It does not submit a Sepolia transaction. Sepolia references attached manually
to an audit are labeled as operator-provided and are not added to its PDF.

The workspace uses browser-native modules and needs no frontend build. Optional
browser checks use `npm ci`, `npx playwright install chromium`, and `npm run test:ui`.

## Run an audit through Swagger

1. As analyst, call `POST /api/audits` with
   `{"scenario":"corridor_audit","idempotency_key":"my-audit-1"}`.
2. Read `GET /api/audits/{audit_id}` until `AWAITING_HUMAN_REVIEW`.
   Inspect the three agent outputs, route checks, evidence and memory comparison.
3. List `GET /api/audits/{audit_id}/reports` and download the draft PDF.
4. Authorize as officer. For each gate, call
   `POST /api/audits/{audit_id}/gates/{gate_id}/decision` with `decision`,
   `reason`, `analysis_digest`, and the latest `expected_revision` from the audit.
   Resolve `final-signoff` last. Read the updated revision after each decision.
5. Wait for `FINALIZED`, then list reports and download the reviewed final PDF.
   Rejected decisions remain visible; finalization does not imply route approval.

Other scenarios are `memory_influence`, `no_suitable_route`, `schema_change`, and
`unsupported_schema`. The memory scenario waits for its eligible precedent to
reach Vector Search. Exhausted retries enter `MANUAL_REVIEW`; an officer can retry
the saved checkpoint with `POST /api/audits/{audit_id}/retry`. Unsupported source
schemas require a new corrected audit, not an approval bypass.

`GET /api/audits/definition` describes the executable audit legs.
`GET /api/audits/{audit_id}/export` includes the hash-linked ledger, immutable
checkpoint artifacts, policy snapshot, and verified report manifests.
Corrections/invalidation remove memory from future retrieval while preserving
historical audit snapshots. Officer-only `/api/control` and `/api/agents/{agent_id}/control`
stop new permits; already permitted uploads can still be reconciled.
Policy proposals under `/api/agent-policies/proposals` need a separate officer
decision. Report sign-off never changes an agent's permissions.

Use a new `chainlex_manual_NAME` namespace for isolated runs. The legacy seed reset
refuses databases containing audit runs/reports to avoid orphaning their history.

## Configuration

All variables have the `CHAINLEX_` prefix; see [`.env.example`](./.env.example).

| Variables | Purpose |
|---|---|
| `MONGODB_URI`, `DATABASE` | Database connection and namespace |
| `DEMO_TENANT_ID`, `ANALYST_TOKEN`, `OFFICER_TOKEN` | Server-bound demo identity and roles |
| `SIMULATOR_URL`, `SIMULATOR_TOKEN` | Simulator connection and separate credential |
| `VOYAGE_API_KEY`, `EMBEDDING_ENDPOINT` | Embedding provider; endpoint must match the key |
| `EMBEDDING_MODEL` | `voyage-finance-2`, 1,024 dimensions |
| `LEASE_SECONDS`, `HEARTBEAT_SECONDS`, `POLL_SECONDS` | Durable worker timing |
| `AUDIT_WORKER_ID` | Stable Change Stream cursor identity; use distinct values for concurrent workers |
| `MAX_STEP_ATTEMPTS`, `RECONCILIATION_SECONDS` | Retry and verification defaults |

The default embedding endpoint is `https://ai.mongodb.com/v1/embeddings` for Atlas
model keys. Voyage platform keys use `https://api.voyageai.com/v1/embeddings`.
LLM and reranking settings are reserved for follow-up live AI integration.
The current demo needs no LLM key. Live web discovery and the operator dashboard
are follow-up work.

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
The live Voyage/Vector Search test additionally requires
`CHAINLEX_TEST_VOYAGE_API_KEY` and optionally `CHAINLEX_TEST_EMBEDDING_ENDPOINT`.

## References

- [FSM states, events, guards, and recovery](./docs/fsm.md)
- [Country corpus, embedding, and bank policies](./docs/country-rules.md)
- [Settlement events and indexing](./docs/settlement-events.md)

## Presentation source material

- [Architecture, six-leg workflow, demo, and roadmap](./chainlex_enriched_hackathon_plan.md)
- [FireFly-inspired architecture and diagrams](./firefly_fsm_chainlex_plan.md)

These plans include proposed capabilities; use the current scope above when describing what the application executes today.
