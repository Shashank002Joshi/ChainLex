# Six-Leg Compliance FSM Scaffold Implementation Plan

> **For agentic workers:** Execute inline, task by task, using the executing-plans workflow. The user approved both the [six-leg design](../specs/2026-11-14-compliance-fsm-design.md) and updates to the plan and scaffold interfaces.

**Goal:** Replace generic job terminology with an event-driven six-leg compliance FSM contract, without claiming durable runtime handlers exist.

**Architecture:** One canonical compliance state determines the leg. A declarative transition catalog records event sources, guards, required writes, safe retry rules, and restart behavior. Internal repository interfaces apply events rather than accepting arbitrary next states; public workflow endpoints remain explicit 501 scaffolds.

**Tech Stack:** Existing Python 3.12, FastAPI, Pydantic, async PyMongo, pytest, and Ruff stack.

## Task 1: Regression tests

Files: `tests/test_fsm.py`, `tests/test_api.py`, `tests/test_domain.py`, `tests/test_mongodb_integration.py`.

- [x] Add the approved 25-event trace, leg derivation, terminal-state, actor-source, wait-resume, and recovery tests before implementation.
- [x] Update route expectations to `/api/fsms`; reject public state/event injection and preserve 401/403/422/501 behavior.
- [x] Run `uv run pytest tests/test_fsm.py`; expect failure because the new FSM contracts do not exist.

```python
rule = transition_for(ComplianceState.SUBMITTING, EventType.START_RECONCILIATION)
assert rule.destination == ComplianceState.RECONCILING
assert "prepared_operation_exists" in rule.guards
```

## Task 2: State, event, and checkpoint contracts

Files: `src/chainlex/domain/fsm.py`, `domain/transitions.py`, `domain/models.py`, `services/contracts.py`.

- [x] Define every state and event from the approved design, six derived legs, terminal states, and runtime-only wait checkpoints.
- [x] Define a source-bound `ComplianceEvent`, immutable artifact references, and a `ComplianceFSM` inspection model with derived leg, last event, wait reason, and artifact references.
- [x] Replace `JobRepository.transition(next_state)` with `ComplianceFSMRepository.apply_event(...)`; document transactional guards and dispatch-permit boundaries.
- [x] Publish transition/state metadata as descriptions, not executable authorization checks.

```python
class ComplianceFSMRepository(Protocol):
    async def apply_event(
        self, fsm: ComplianceFSM, event: ComplianceEvent, lease: Lease | None
    ) -> ComplianceFSM: ...
```

## Task 3: API, bootstrap, and configuration

Files: `src/chainlex/api/app.py`, `api/static/index.html`, `db/indexes.py`, `config.py`, `.env.example`, `worker/main.py`.

- [x] Replace `/api/jobs` route contracts with `/api/fsms`; add an authenticated, read-only `/api/fsms/definition` endpoint to inspect the static FSM catalog.
- [x] Keep unimplemented instance operations at 501 and keep instance creation free of caller-controlled tenant, state, and transition fields.
- [x] Replace new bootstrap collection references with `compliance_fsms` and `fsm_id`; define unique audit event/sequence keys and a tenant governance-control record.
- [x] Preserve legacy collections and indexes; no live Atlas migration or deletion is part of this work.
- [x] Add three-attempt retry and 120-second reconciliation defaults; update worker logging to identify the idle FSM scaffold.

## Task 4: Plan and manual-test documentation

Files: `chainlex_enriched_hackathon_plan.md`, `README.md`, `docs/scaffold-verification.md`, approved design.

- [x] Replace the enriched plan's generic state chain with the six exact legs and their checkpoint/recovery contracts.
- [x] Document current state/event definitions, `/api/fsms/definition`, manual HTTP checks, route naming changes, and the unchanged runtime implementation boundary.
- [x] Record the static definition endpoint and the explicit finalization-retry path in the design so code and documentation agree.

## Task 5: Verify

- [x] Run `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, `uv build`, and `docker compose config --quiet`.
- [x] Run the existing real MongoDB integration suite against its uniquely named disposable database; test bootstrap repeatability and legacy-record preservation.
- [x] Inspect the built wheel for the new domain module and static page; confirm Git still ignores `.env`.
- [x] Review state/event coverage against each approved leg and confirm no placeholder is presented as executed policy or recovery logic.

Runtime retrieval, policy evaluation, atomic transition execution, fenced worker processing, external submissions through the FSM, and full recovery demonstrations remain the next implementation phase.
