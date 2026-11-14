# Manual testing: six-leg FSM scaffold and MongoDB

This runbook covers the current scaffold: startup, database setup, the six-leg FSM definition, authentication, and persistent simulator holds. The FSM instance handlers still return `501 WORKFLOW_NOT_IMPLEMENTED`; they do not yet advance a settlement through the six legs.

Use the Atlas connection and tokens already saved in `.env`. These steps use a separate database, **`chainlex_manual_fsm`**, on that cluster so manual-test counts are easy to inspect. Set the database variable in **every terminal** shown below. The commands do not change `.env`. Docker is not required when using Atlas.

## 1. Prepare and initialize the manual-test database

In a terminal:

```sh
cd /Users/devchetal/ChainLex
export CHAINLEX_DATABASE=chainlex_manual_fsm
uv sync --locked --group dev
uv run chainlex-db preflight
uv run chainlex-db bootstrap
uv run chainlex-db seed-demo
```

Expected output:

- Preflight reports `database: reachable`, `topology: transaction_capable`, and `transaction: committed`.
- Bootstrap reports `bootstrap: complete`.
- Seed reports six entities, four cases, and `review_status: UNVERIFIED`.

Confirm the selected namespace and tenant without printing credentials:

```sh
uv run python - <<'PY'
from chainlex.config import Settings
settings = Settings()
print("Database:", settings.database)
print("Demo tenant:", settings.demo_tenant_id)
assert settings.analyst_token.get_secret_value(), "Configure CHAINLEX_ANALYST_TOKEN"
assert settings.officer_token.get_secret_value(), "Configure CHAINLEX_OFFICER_TOKEN"
assert settings.simulator_token.get_secret_value(), "Configure CHAINLEX_SIMULATOR_TOKEN"
PY
```

Expected database: `chainlex_manual_fsm`. The default demo tenant is `bank_a`.

The seed command is repeatable: rerunning it preserves the same six fixture entities and four fixture cases rather than creating duplicates. In an already-used database, existing edits to those fixtures are preserved.

If bootstrap reports a legacy unique `job_id` index, stop that setup attempt. It requires a separately reviewed migration. Use a fresh database name consistently in all terminals to continue this manual test. Setup does not migrate or remove existing collections or indexes; the optional seed reset below also preserves them.

## 2. Start the API and simulator

Terminal A — API:

```sh
cd /Users/devchetal/ChainLex
export CHAINLEX_DATABASE=chainlex_manual_fsm
uv run chainlex-api --port 8000
```

Terminal B — simulator:

```sh
cd /Users/devchetal/ChainLex
export CHAINLEX_DATABASE=chainlex_manual_fsm
uv run chainlex-simulator --port 8001
```

Keep both running. Restart them after code or environment changes; the commands do not enable automatic reload.

Terminal C — worker startup check:

```sh
cd /Users/devchetal/ChainLex
export CHAINLEX_DATABASE=chainlex_manual_fsm
uv run chainlex-worker --once
```

Expected log: `worker=fsm_scaffold_idle database=ready fsm_processing=not_implemented`. This command exits after startup validation and does not create FSM records.

For all remaining terminal commands, continue in Terminal C with the same database variable set.

## 3. Check service health

```sh
curl -i http://127.0.0.1:8000/health/live
curl -i http://127.0.0.1:8000/health/ready
curl -i http://127.0.0.1:8001/health/live
curl -i http://127.0.0.1:8001/health/ready
```

All four responses should be HTTP `200`. Readiness includes `database: reachable` and `workflow: scaffold`; it does not certify implemented compliance handlers.

Browser pages:

- API status: <http://127.0.0.1:8000/>
- API documentation: <http://127.0.0.1:8000/docs>
- Simulator documentation: <http://127.0.0.1:8001/docs>

For Swagger's **Authorize** control, use the analyst token from `.env` for normal API requests and the officer token for governance requests. The simulator has its own token on its separate documentation page. The scripts below load tokens automatically and do not print them.

## 4. Inspect each FSM leg and check the API boundary

Run this in Terminal C. It performs read-only definition checks and sends requests that the current scaffold rejects without creating FSMs:

```sh
uv run python - <<'PY'
import os
import httpx
from chainlex.config import Settings

settings = Settings()
api_url = os.environ.get("CHAINLEX_MANUAL_API_URL", "http://127.0.0.1:8000")
analyst = {"Authorization": f"Bearer {settings.analyst_token.get_secret_value()}"}

with httpx.Client(base_url=api_url, timeout=15) as client:
    response = client.get("/api/fsms/definition")
    assert response.status_code == 401
    print("Missing token:", response.status_code)

    response = client.get("/api/fsms/definition", headers=analyst)
    response.raise_for_status()
    definition = response.json()
    assert len(definition["legs"]) == 6
    assert definition["runtime_implemented"] is False
    assert definition["guards_evaluated"] is False
    for leg, states in definition["legs"].items():
        print(leg, "→".join(states))
    for state in ("SUBMITTING", "SUBMISSION_UNKNOWN", "FINALIZING"):
        print(state, "recovery:", definition["states"][state]["recovery"])

    for event in ("OFFICER_APPROVED", "SUBMISSION_PERMITTED", "EFFECT_VERIFIED"):
        for transition in definition["transitions"]:
            if transition["event"] == event:
                print(event, "guards:", transition["guards"], "writes:", transition["writes"])

    body = {"scenario": "automatic_hold", "idempotency_key": "manual-fsm-001"}
    response = client.post("/api/fsms", headers=analyst, json=body)
    assert response.status_code == 501
    assert response.json()["detail"]["code"] == "WORKFLOW_NOT_IMPLEMENTED"
    print("FSM creation is scaffolded:", response.status_code)

    response = client.post("/api/fsms", headers=analyst, json=body | {"state": "AUTHORIZED"})
    assert response.status_code == 422
    print("Caller-supplied state rejected:", response.status_code)

    response = client.post(
        "/api/proposals/manual-proposal/decision", headers=analyst,
        json={"decision": "APPROVE", "proposal_version": 1, "reason": "Manual role check"},
    )
    assert response.status_code == 403
    print("Analyst cannot approve:", response.status_code)
PY
```

Check these semantics in the definition output:

| Leg | What to inspect |
|---|---|
| Intake | Validation precedes party/jurisdiction resolution; context is saved before retrieval. |
| Evidence | Embedding, regulation search, precedent search, reranking, and validation are separate states. |
| Analysis | Candidate generation and citation validation are separate states. |
| Authorization | Officer approval returns to `EVALUATING_POLICY`; it does not jump to dispatch. |
| Dispatch | `SUBMISSION_PERMITTED` requires current authorization and an unpaused tenant control revision. |
| Verification | A receipt and observed held effect are required before finalization; submission uncertainty probes the saved operation. |

`SUBMITTING` and `SUBMISSION_UNKNOWN` should report `probe_saved_operation`. `FINALIZING` should report `retry_local_finalization`.

These are contract checks. Reading the definition does not evaluate guards, write audit events, create an outbox action, or move an FSM through states.

## 5. Send and verify one fictional hold

This script calls the simulator directly. It creates **one fictional hold operation** in the selected database; it does not submit a blockchain transaction or exercise the unimplemented FSM authorization path.

```sh
uv run python - <<'PY'
import time
import httpx
from chainlex.config import Settings
from chainlex.connectors.simulator import prepare_action
from chainlex.domain.models import HoldAction

settings = Settings()
action = HoldAction(
    tenant_id=settings.demo_tenant_id,
    settlement_id="manual-settlement-001",
    amount_minor=10_000_000,
)
prepared = prepare_action(action, "manual-hold-001")
headers = {"Authorization": f"Bearer {settings.simulator_token.get_secret_value()}"}

with httpx.Client(base_url=settings.simulator_url, timeout=15) as client:
    for attempt in range(2):
        response = client.post("/operations", headers=headers, json=prepared.model_dump(mode="json"))
        response.raise_for_status()
        assert response.json()["operation_id"] == prepared.operation_id
        print(f"Dispatch {attempt + 1}:", response.json())

    response = client.get(
        f"/operations/{prepared.operation_id}", headers=headers,
        params={"tenant_id": settings.demo_tenant_id},
    )
    response.raise_for_status()
    print("Initial probe:", response.json())

    time.sleep(settings.simulator_confirmation_seconds + 0.5)
    response = client.get(
        f"/operations/{prepared.operation_id}", headers=headers,
        params={"tenant_id": settings.demo_tenant_id},
    )
    response.raise_for_status()
    result = response.json()
    assert result["outcome"] == "CONFIRMED" and result["effect"] == "HELD"
    assert result["settlement_id"] == action.settlement_id
    print("Confirmed:", result)

    response = client.get(
        f"/operations/{prepared.operation_id}", headers=headers,
        params={"tenant_id": settings.demo_tenant_id + "_other"},
    )
    response.raise_for_status()
    assert response.json()["outcome"] == "NOT_FOUND"
    print("Other tenant cannot probe this operation:", response.json()["outcome"])

    changed = prepare_action(
        action.model_copy(update={"settlement_id": "manual-settlement-different"}),
        "manual-hold-001",
    )
    response = client.post("/operations", headers=headers, json=changed.model_dump(mode="json"))
    assert response.status_code == 409
    print("Conflicting payload rejected:", response.status_code)

    tampered = prepared.model_copy(update={"payload_digest": "0" * 64})
    response = client.post("/operations", headers=headers, json=tampered.model_dump(mode="json"))
    assert response.status_code == 422
    print("Tampered digest rejected:", response.status_code)
PY
```

Expected: both dispatches return the same operation ID; the later probe returns `CONFIRMED` and `HELD`. The first probe may already be confirmed if the operation was created in an earlier run. USD 100,000 is represented as 10,000,000 minor units.

## 6. Inspect MongoDB collections and documents

Connect with Atlas's database browser, MongoDB Compass, or an existing `mongosh` connection to the configured cluster. Select **`chainlex_manual_fsm`**. If you used another database name, use that name throughout this section.

In `mongosh`:

```javascript
use chainlex_manual_fsm
db.getCollectionNames().sort()
```

For a fresh manual-test namespace, expect these results after steps 1–5:

| Collection | Expected contents |
|---|---|
| `entities` | Six fictional records; three for `bank_a` and three for `bank_b`. |
| `compliance_cases` | Four historical fixtures; two per tenant, all `UNVERIFIED` and `is_active: false`. |
| `simulator_operations` | One record for the current tenant and `manual-hold-001`. |
| `compliance_fsms` | Empty: instance creation returned 501. |
| `agent_action_proposals` | Empty: the FSM policy/approval handlers are absent. |
| `tx_outbox` | Empty: direct simulator calls do not create outbox actions. |
| `audit_ledger` | Empty: no durable FSM transitions ran. |
| `policies` | Empty: bootstrap does not seed executable policies. |
| `tenant_controls` | Empty: bootstrap defines the collection/index, not an active control record. |
| `regulations` | Empty: verified regulatory ingestion is not implemented. |
| `chain_blocks`, `chain_transactions`, `contract_events` | Empty during this simulator walkthrough; these are populated only when the separate blockchain indexer is used. |

An additional `_preflight` collection may exist with zero documents. Preflight deletes its temporary marker after the transaction check.

### Seed data and tenant separation

```javascript
db.entities.countDocuments({is_demo_fixture: true})
// 6

db.entities.aggregate([
  {$match: {is_demo_fixture: true}},
  {$group: {_id: "$tenant_id", count: {$sum: 1}}},
  {$sort: {_id: 1}}
])
// bank_a: 3; bank_b: 3

db.compliance_cases.find(
  {is_demo_fixture: true},
  {_id: 1, tenant_id: 1, review_status: 1, is_active: 1}
)
// Four fixture records, UNVERIFIED, is_active: false.
```

### The saved simulator effect

The following filter assumes the default demo tenant `bank_a`. Replace that value if the settings check in step 1 printed another demo tenant. The fixture seed itself always uses `bank_a` and `bank_b`.

```javascript
db.simulator_operations.find(
  {tenant_id: "bank_a", idempotency_key: "manual-hold-001"},
  {
    _id: 1,
    tenant_id: 1,
    schema_version: 1,
    idempotency_key: 1,
    payload_digest: 1,
    action: 1,
    effect: 1,
    created_at: 1,
    confirmed_at: 1,
    is_simulated: 1
  }
)

db.simulator_operations.countDocuments({
  tenant_id: "bank_a", idempotency_key: "manual-hold-001"
})
// 1, even after both dispatches and the rejected conflicting requests.
```

Check:

- `_id` matches the operation ID printed by the script.
- `schema_version` is `1`; `is_simulated` is `true`.
- `action.settlement_id` and `effect.settlement_id` both equal `manual-settlement-001`.
- `action.action_type` is `HOLD_SETTLEMENT`; `amount_minor` is `10000000`; currency is `USD`.
- `effect.status` is `HELD`.
- `payload_digest` is a 64-character hexadecimal string.
- `created_at` and `confirmed_at` are BSON dates. `confirmed_at` is the scheduled confirmation time, not a blockchain receipt.
- The conflicting request did not replace the target with `manual-settlement-different`.

There is no persisted `outcome: CONFIRMED` field. The probe computes that outcome from the stored confirmation time and saved effect.

### FSM runtime collections remain empty

```javascript
db.compliance_fsms.countDocuments({})
db.agent_action_proposals.countDocuments({})
db.tx_outbox.countDocuments({})
db.audit_ledger.countDocuments({})
db.tenant_controls.countDocuments({})
// Each should be 0 in this fresh namespace.
```

The six-leg definition is application code, not an FSM instance stored in MongoDB. This manual test does not produce documents in states such as `RECEIVED`, `AUTHORIZED`, or `FINALIZED`.

### Indexes and collection validation

```javascript
db.compliance_fsms.getIndexes()
// request_key: unique (tenant_id, idempotency_key)
// fsm_identity: unique (tenant_id, fsm_id)
// recoverable_fsms: (state, runtime.lease.expires_at)

db.audit_ledger.getIndexes()
// fsm_audit_sequence: unique (tenant_id, fsm_id, sequence)
// fsm_audit_event: unique (tenant_id, fsm_id, event_id), filtered to string event IDs

db.simulator_operations.getIndexes()
// sim_action_key: unique (tenant_id, idempotency_key)

db.tenant_controls.getIndexes()
// tenant_control: unique (tenant_id)

db.getCollectionInfos({name: "compliance_fsms"})[0].options.validator
// The common validator requires tenant_id and schema_version.
```

These are ordinary MongoDB indexes. Bootstrap does not create Atlas Vector Search indexes. The common validator does not implement the FSM's policy or transition guards.

In Compass, the equivalent operation filter is:

```json
{"tenant_id": "bank_a", "idempotency_key": "manual-hold-001"}
```

Inspect the document fields and the collection's indexes using the same expectations above.

## 7. Verify persistence after simulator restart

1. Note the operation's `_id`, `created_at`, `confirmed_at`, and document count in MongoDB.
2. Stop only the simulator in Terminal B with `Ctrl+C`.
3. Restart it from that terminal with the same namespace:

```sh
uv run chainlex-simulator --port 8001
```

4. Rerun the script in step 5 unchanged.
5. Both submissions should return the original ID; the probe should return `CONFIRMED`.
6. Recheck MongoDB: the matching operation count is still one, and its creation/confirmation timestamps and target remain unchanged.

This proves persistence and idempotency of the simulator across its own process restart. Worker crash recovery through the compliance FSM is a later runtime feature.

## 8. Stop services

Stop the API and simulator with `Ctrl+C`. Stop any continuously running worker too; a worker run with `--once` has already exited. Manual-test records remain available in `chainlex_manual_fsm` for inspection until you choose to reset them below.

## 9. Optional: reset through the seed command

Normal `seed-demo` remains idempotent: it inserts missing fixtures, preserves existing fixture edits, and leaves run records alone. Use its explicit reset mode when you want another manual run from the original fixture state.

First preview the exact runtime deletion counts and fixture IDs that will be restored:

```sh
uv run chainlex-db seed-demo --reset --database chainlex_manual_fsm
```

Expect `mode: preview`. This does not delete records or modify fixtures. Check the reported database and `would_delete_runtime` counts before executing:

```sh
uv run chainlex-db seed-demo --reset --database chainlex_manual_fsm --execute --confirm-db chainlex_manual_fsm
```

This resets only the explicitly selected `chainlex_manual_*` database:

| Data | Reset behavior |
|---|---|
| `compliance_fsms`, `agent_action_proposals`, `tx_outbox`, `audit_ledger`, `simulator_operations` | Clear all records in these five collections, across tenants within the selected manual-test database. |
| `demo-entity-1` through `demo-entity-6` | Restore the original six entity fixture documents, including removal of added fixture fields. |
| `demo-case-1` through `demo-case-4` | Restore the original four inactive, unverified case fixture documents. |
| Other entity and case records | Preserve. |
| `regulations`, `policies`, `tenant_controls`, blockchain/indexer collections, and other collections | Preserve their contents. |
| Collections, indexes, and validators | Preserve. |

Deletion and fixture restoration run in one MongoDB transaction. A failure aborts both. Reset refuses a known fixture ID if its existing record is no longer marked `is_demo_fixture: true`; it does not silently replace a non-demo record.

The reset requires an explicit `--database`; it cannot silently use the default `.env` database. Names outside `chainlex_manual_*`, a missing execution confirmation, or a mismatched confirmation are rejected. It is not a legacy-index migration and will not drop a database.

After a successful execution, expect `mode: reset`, actual `deleted_runtime` counts, and `restored` counts of six entities and four cases. Check MongoDB:

```javascript
use chainlex_manual_fsm
db.simulator_operations.countDocuments({})
db.compliance_fsms.countDocuments({})
db.agent_action_proposals.countDocuments({})
db.tx_outbox.countDocuments({})
db.audit_ledger.countDocuments({})
// Each is 0 while services remain stopped.

db.entities.countDocuments({is_demo_fixture: true})
// 6
db.compliance_cases.countDocuments({
  is_demo_fixture: true, review_status: "UNVERIFIED", is_active: false
})
// 4
db.simulator_operations.getIndexes()
// sim_action_key is still present and unique.
```

Existing policies, controls, regulations, and non-fixture records remain, so their total collection counts need not be zero. Restart services using step 2, then repeat the simulator script in step 5. Its stable operation ID will be the same, but this fresh operation will have new creation/confirmation timestamps.

## 10. Summarize your results

Passing checklist:

- [ ] Database preflight, bootstrap, and fixture seeding succeed.
- [ ] All four liveness/readiness checks return 200.
- [ ] Definition shows six legs and precise states, guards, outputs, and recovery rules.
- [ ] Missing token, injected state, and analyst approval attempts return 401, 422, and 403.
- [ ] FSM creation returns the documented 501 boundary and creates no FSM record.
- [ ] Simulator duplicate dispatch returns one operation; wrong tenant probe returns `NOT_FOUND`.
- [ ] Changed target with the same key returns 409; tampered digest returns 422.
- [ ] MongoDB contains the expected fixtures, one correctly scoped held effect, and the defined indexes.
- [ ] Simulator restart preserves that same operation and timestamps.
- [ ] If reset was requested, preview was read-only; confirmed execution cleared runtime records, restored the ten fixtures, and retained indexes.

If a request fails, check that both services and your test terminal use the same database and cluster. `401` means the service token does not match; readiness `503` means database configuration/connectivity needs attention. `Address already in use` usually means an older service still occupies the port. A 501 from a documented instance/governance route is expected at this stage.
