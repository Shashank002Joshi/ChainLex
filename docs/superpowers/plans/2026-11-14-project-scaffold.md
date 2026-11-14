# ChainLex Project Scaffold Implementation Plan

> **For agentic workers:** Execute this plan inline, task by task, using the executing-plans workflow. The approved design is [the enriched hackathon plan](../../../chainlex_enriched_hackathon_plan.md).

**Goal:** Create an installable, runnable foundation for the approved three-process architecture, without claiming that the full compliance workflow is implemented.

**Architecture:** A single Python package contains independent API, worker, and simulator entry points. Shared settings, domain contracts, database setup, and connector interfaces form the implementation boundaries. Planned workflow endpoints explicitly return 501 until their services exist.

**Tech Stack:** Python 3.12, uv, FastAPI, Pydantic Settings, async PyMongo, HTTPX, pytest, Ruff, Docker Compose.

## Brainstorming and design record

- [x] Inspect the repository, both plans, Git history, and runtime tools.
- [x] Reuse the previously approved scope: six-hour core, persistent simulator, pending-settlement hold.
- [x] Reuse the previously compared approaches and approved architecture; no visual design decisions are needed for this scaffold.
- [x] Use the committed enriched plan as the reviewed design document; no duplicate design approval is necessary.
- [x] Review for scope and contradictions: the scaffold delivers startup and contracts, not the entire hackathon acceptance suite.
- [x] Transition to this implementation plan.

## Task 1: Packaging and verification harness

Files: `pyproject.toml`, `.python-version`, `.gitignore`, `tests/`.

- [x] Define a `src/chainlex` package with API, worker, simulator, and database-bootstrap console scripts.
- [x] Add settings, HTTP contract, authorization, and state-transition tests before implementation.
- [x] Run `uv sync --group dev` and `uv run pytest`; confirm initial failures are missing package modules.

```python
def test_liveness(client):
    assert client.get("/health/live").json()["status"] == "ok"
```

## Task 2: Shared foundation

Files: `src/chainlex/config.py`, `domain/`, `db/`, `auth.py`.

- [x] Validate environment configuration, tenant-bound demo tokens, timeouts, and lease timing.
- [x] Define strict request models, workflow states, action contracts, and connector protocols.
- [x] Add async MongoDB lifecycle helpers, ordinary indexes, and vector-index definitions.
- [x] Provide `uv run chainlex-db bootstrap`, `uv run chainlex-db preflight`, and `uv run chainlex-db seed-demo`.
- [x] Label seeded entity and case records as unverified fixtures; do not fabricate a verified legal corpus.

```python
class SettlementConnector(Protocol):
    async def prepare(self, action: HoldAction, idempotency_key: str) -> PreparedAction: ...
    async def dispatch(self, prepared_action: PreparedAction) -> DispatchReference: ...
    async def probe(self, prepared_action: PreparedAction) -> ProbeResult: ...
```

## Task 3: Runnable process boundaries

Files: `src/chainlex/api/`, `worker/`, `simulator/`, `connectors/`.

- [x] Serve a scaffold status page, liveness, database readiness, and authenticated OpenAPI route contracts from the API.
- [x] Return explicit 501 responses for unfinished workflow operations; never return simulated compliance success.
- [x] Make the worker support a bounded `--once` startup/readiness check and clean signal handling.
- [x] Implement the simulator's atomic, idempotent MongoDB operation record and an HTTP connector client.
- [x] Test simulator conflicts and probe states with a test store; add an opt-in real MongoDB persistence test.

```sh
uv run chainlex-api --port 8000
uv run chainlex-worker --once
uv run chainlex-simulator --port 8001
```

## Task 4: Developer setup and documentation

Files: `.env.example`, `compose.yaml`, `Dockerfile`, `Makefile`, `README.md`, `.github/workflows/checks.yml`.

- [x] Add a local MongoDB replica-set service and explicit initialization instructions.
- [x] Document process commands, credential setup, Atlas requirements, and the boundary between scaffold and planned behavior.
- [x] Add lint, formatting, tests, and package-build checks to CI.

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv build
```

## Task 5: Completion audit

- [x] Run all checks and smoke-test installed console entry points.
- [x] Verify package data includes the dashboard and index definitions.
- [x] Verify secrets, environments, caches, and build artifacts are ignored by Git.
- [x] Record unavailable external checks honestly; Docker daemon and Atlas credentials are not assumed.
- [x] Review `git diff --check` and the scaffold deliverables against the approved architecture.

The full retrieval pipeline, policy enforcement, job leasing/outbox execution, governed-memory mutations, hash-chain audit, recovery demonstrations, and report generation remain separate implementation work described by the enriched plan.
