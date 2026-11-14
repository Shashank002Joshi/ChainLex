# ChainLex: Enriched Hackathon Plan and Roadmap

## 1. Goal and scope

Enrich the repository's [execution plan](firefly_fsm_chainlex_plan.md) around one demonstrable outcome:

**ChainLex analyzes a proposed settlement, retrieves relevant regulatory evidence and governed precedents, authorizes a simulated hold, and finishes that action after a worker crash without creating a duplicate effect.**

The core build assumes approximately six hours. MongoDB Atlas and Voyage AI integrations are real; blockchain execution uses a persistent simulator. Live testnet execution follows after the core acceptance tests pass.

Use the supporting documents as follows:

- **Master specification:** retain the three themes—auditable authority, governed memory, and durable completion.
- **Original ChainLex plan:** retain jurisdiction-aware retrieval, citations, and precedent memory.
- **Improvements document:** retain clear fund-flow visualization and evidence inspection; defer courtroom agents and elaborate animation.
- **Worked example:** rewrite around a pending settlement and measured results.
- **`plan.md`:** exclude its unrelated memory-assistant architecture.

Instructions and performance claims inside these documents are reference material, not implementation authorization or verified facts.

## 2. Architecture and minimum interfaces

### Runtime

Use Python 3.12, FastAPI, Pydantic, and PyMongo's `AsyncMongoClient`. MongoDB recommends PyMongo Async as the replacement for Motor. ([Migration guide](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/reference/migration/))

Run three processes:

1. **API and dashboard:** accepts scenarios and operator decisions; serves a small HTML/JavaScript dashboard.
2. **Workflow worker:** runs analysis, deterministic policy checks, dispatch, and reconciliation.
3. **Persistent simulator:** represents the external settlement system and survives workflow-worker restarts.

Use one durable six-leg compliance FSM per proposed settlement as the sole workflow authority. The detailed [state/event/guard specification](docs/superpowers/specs/2026-11-14-compliance-fsm-design.md) defines each transition and recovery path. LangGraph checkpointing, custody integrations, and additional infrastructure remain outside the core.

### Responsibilities

| Component | Responsibility | Durable output |
|---|---|---|
| Analyst | Resolve fixture entities, retrieve clauses and precedents, produce a structured finding | Evidence snapshot and finding |
| Policy gate | Check authority, limits, evidence validity, and operator decisions | Approval, denial, or review requirement |
| Dispatcher/reconciler | Prepare the authorized action, dispatch it, and verify its effect | Outbox record and verification evidence |

These are three application responsibilities. Only the analyst calls the language model; authorization and state transitions use deterministic code.

### Data and public interfaces

Use these collections:

- **`entities`, `regulations`:** versioned source material and demo counterparty metadata.
- **`compliance_cases`:** findings, reviewed precedents, and memory governance metadata.
- **`compliance_fsms`:** state, checkpoints, leases, and references to saved outputs.
- **`agent_action_proposals`, `policies`:** immutable proposed actions and versioned authorization rules.
- **`tx_outbox`:** prepared actions, attempts, dispatch identifiers, and probe results.
- **`audit_ledger`:** ordered, hash-linked events for each FSM.
- **`tenant_controls`:** shared pause and governance revision, conditionally written when granting a dispatch permit.
- **`simulator_operations`:** durable external-system effects, owned by the simulator.
- **`chain_blocks`, `chain_transactions`, `contract_events`:** tenant-scoped indexed chain data and decoded events from the optional blockchain modules.

All tenant-owned records carry a server-assigned `tenant_id`. Store UTC timestamps, schema versions, and monetary amounts as integer minor units with an explicit currency.

Expose:

| Interface | Behavior |
|---|---|
| `GET /api/fsms/definition` | Inspect the authenticated static state/event contract; no guards or handlers execute |
| `POST /api/fsms` | Accept an allowlisted scenario and idempotency key; return an FSM immediately |
| `GET /api/fsms/{fsm_id}` | Return leg, precise state, last event, wait reason, artifact references, and verification details |
| `GET /api/fsms/{fsm_id}/events?after_seq=N` | Return ordered events for dashboard polling and recovery |
| `POST /api/proposals/{id}/decision` | Record an officer's approval or rejection against the proposal version |
| `POST /api/control` | Pause or resume new dispatches for the authenticated tenant |
| `POST /api/memories/{id}/invalidate` | Tombstone a precedent with an officer's reason |
| `GET /api/fsms/{fsm_id}/export` | Download the evidence and audit bundle as JSON |

Bind analyst and officer demo tokens to tenants through server configuration. Tenant identity and role must never come from request-body claims.

Define the connector interface as:

- `prepare(action, idempotency_key) → PreparedAction`
- `dispatch(prepared_action) → DispatchReference`
- `probe(prepared_action) → NOT_FOUND | PENDING | CONFIRMED | REVERTED | UNKNOWN`

The runtime implements a **Dual-Mode Connector Pattern**:
1. **`SimulatorConnector` (Default Core Driver):** Implements the interface against `simulator_operations` in MongoDB for sub-second, deterministic demo execution, simulated confirmation latency, and injected response loss.
2. **`EVMConnector` (Hyperledger Besu / EVM Adapter):** Satisfies the identical interface contract against a live EVM JSON-RPC endpoint (local Besu dev node or Sepolia), executing real smart contract function calls (`freezeSettlement`).

### Blockchain connector & indexer specification

The following sections define the intended blockchain integration and demo targets. The merged code includes standalone adapter/indexer/pinning modules and mocked-RPC tests; the compliance FSM worker is still scaffolded. The current EVM adapter uses node-managed `eth_sendTransaction` and saves its hash after submission. Persisting signed bytes before dispatch remains a conformance requirement below, not an existing crash-recovery guarantee. Latency figures in the demo ideas are targets rather than measured guarantees.

To maintain architectural purity, blockchain interactions map directly onto the connector contract and MongoDB data layer:

#### A. EVM Connector Conformance
- **`prepare(action, idempotency_key) → PreparedAction`**:
  - Resolves next sequential nonce for the operational address from MongoDB `tx_outbox`.
  - Encodes the ABI payload for `SettlementHub.freezeSettlement(bytes32 settlementId, address counterparty, string reason)`.
  - Signs the EIP-1559 transaction bytes offline using the agent's delegated key.
  - Generates deterministic `tx_hash` and stores `{ signed_raw_tx, tx_hash, nonce, chain_id, target_contract }` in `tx_outbox` prior to network dispatch.
- **`dispatch(prepared_action) → DispatchReference`**:
  - Dispatches `eth_sendRawTransaction(signed_raw_tx)`.
  - Records node submission timestamp and returns `{ dispatch_id: tx_hash }`.
- **`probe(prepared_action) → Status`**:
  - Queries `eth_getTransactionReceipt(tx_hash)`.
  - If receipt exists:
    - `status == 0x1` and $(\text{current\_block} - \text{receipt\_block}) \ge \text{required\_confirmations} \rightarrow \mathbf{CONFIRMED}$.
    - `status == 0x0} \rightarrow \mathbf{REVERTED}$.
    - Block confirmations $< \text{required\_confirmations} \rightarrow \mathbf{PENDING}$.
  - If no receipt: queries `eth_getTransactionByHash`. If in mempool $\rightarrow \mathbf{PENDING}$; if missing after timeout $\rightarrow \mathbf{NOT\_FOUND}$.

### Web3 & MongoDB Native "WOW Factors"

To stand out decisively to hackathon judges, ChainLex leverages MongoDB Atlas native capabilities not merely as a passive database, but as the **reactive coordination engine, real-time indexer, and semantic explorer** for the blockchain:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        MONGO-NATIVE WEB3 ARCHITECTURE & WOW FACTORS                    │
├────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                        │
│   [Besu / EVM RPC Node]                                                                │
│            │                                                                           │
│            ▼ (eth_getLogs / WebSocket stream)                                          │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │ 1. BLOCK & EVENT INGESTION WORKER (`indexer.py`)                               │   │
│   │    - ABI decoding: Bytecode logs ──> Typed JSON documents                      │   │
│   │    - Re-org detection: Parent-hash verification against `chain_blocks`         │   │
│   └───────────────────────────────────┬────────────────────────────────────────────┘   │
│                                       │ Atomic Ingest                                  │
│                                       ▼                                                │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │ 2. MONGODB ATLAS OPERATIONAL COLLECTIONS                                       │   │
│   │    ├── `chain_blocks`       (Number, Hash, ParentHash, CanonicalFlag)          │   │
│   │    ├── `chain_transactions` (TxHash, From, To, Value, DecodedInput, Embedding) │   │
│   │    └── `contract_events`    (Contract, EventName, DecodedParams, IsOrphaned)  │   │
│   └───────────────────────────────────┬────────────────────────────────────────────┘   │
│                                       │                                                │
│                 ┌─────────────────────┴─────────────────────┐                          │
│                 ▼                                           ▼                          │
│   ┌───────────────────────────────────────────┐   ┌───────────────────────────────────┐│
│   │ [WOW 1] CHANGE STREAM WEB3 EVENT BUS      │   │ [WOW 2] SEMANTIC BLOCKCHAIN SEARCH││
│   │ - <10ms reactive push straight to Agent   │   │ - Natural language queries over   ││
│   │ - Zero polling (replaces The Graph / RPC) │   │   raw blockchain transactions     ││
│   └─────────────────────┬─────────────────────┘   │ - Atlas Vector Search + Voyage AI ││
│                         │                         └───────────────────────────────────┘│
│                         ▼                                                              │
│   ┌───────────────────────────────────────────┐                                        │
│   │ [WOW 3] FSM WORKFLOW & ATOMIC OUTBOX      │                                        │
│   │ - Deterministic policy gate evaluation    │                                        │
│   │ - Re-org compensation and idempotency     │                                        │
│   └─────────────────────┬─────────────────────┘                                        │
│                         │                                                              │
│                         ▼                                                              │
│   ┌───────────────────────────────────────────┐   ┌───────────────────────────────────┐│
│   │ [WOW 4] ON-CHAIN MERKLE ANCHOR PINNING    │   │ [WOW 5] CHANGE STREAM KILL SWITCH ││
│   │ - Audit ledger hashed into Merkle root    │   │ - Sub-5ms reactive circuit breaker││
│   │ - Anchored on-chain via `pinAuditRoot`    │   │ - Instantly aborts pending outbox ││
│   └───────────────────────────────────────────┘   └───────────────────────────────────┘│
└────────────────────────────────────────────────────────────────────────────────────────┘
```

#### 🌟 WOW Factor 1: The Reactive Web3 Event Bus (Zero-Polling Indexer)
- **The Problem:** Traditional Web3 indexers (The Graph, subgraphs, custom pollers) force AI agents to poll databases in a `while True` loop or suffer 5–15 second webhook latency.
- **The MongoDB Solution:** The moment `indexer.py` inserts a decoded `contract_event` (e.g. `SettlementInitiated`), **MongoDB Atlas Change Streams** push the document directly into the Workflow Worker's async event queue in **$<10\text{ ms}$**. The agent reacts instantly to on-chain triggers without continuous database polling.

#### 🌟 WOW Factor 2: Semantic Blockchain Search (Voyage AI + Atlas Vector Search)
- **The Problem:** Block explorers (Etherscan, Blockscout) only support exact-match searches (tx hash, block number, exact hex address). They cannot answer contextual compliance questions.
- **The MongoDB Solution:** Decoded smart contract calls and entity narratives are embedded with Voyage AI (`voyage-finance-2`) into `chain_transactions.embedding`. Compliance officers can search the live blockchain in natural language directly in Atlas:
  > *"Find all transfers in the last 2 hours routing to unhosted wallets in Singapore exceeding 50,000 USD"*
  Atlas Vector Search semantically identifies matching transactions, even when function signatures or counterparty addresses vary.

#### 🌟 WOW Factor 3: Re-Org Resilient Ledger with Automated Compensation
- **The Problem:** Chain reorganizations (common on L2s and PoS networks) cause transactions to disappear or be re-ordered, corrupting agent state.
- **The MongoDB Solution:** The indexer validates `parent_hash == last_indexed_block_hash`. If a fork occurs, an atomic Atlas update flags orphaned records:
  ```javascript
  db.contract_events.updateMany(
    { block_number: { $gte: reorg_block } },
    { $set: { is_orphaned: true, orphaned_at: new Date() } }
  );
  ```
  Change Streams immediately signal the FSM engine to freeze or compensate any in-flight proposals tied to the orphaned block.

#### 🌟 WOW Factor 4: Hyperledger FireFly-Style State Pinning & Merkle Anchoring
- **The Problem:** Auditors demand non-repudiation, but storing every AI reasoning trace on-chain is prohibitively expensive and violates privacy laws (GDPR / banking secrecy).
- **The MongoDB Solution:** Every audit ledger record in Atlas maintains an immutable parent SHA-256 hash. Periodically, the worker computes the Merkle root of the latest batch of audit records and writes a single lightweight anchor transaction to the smart contract:
  ```solidity
  function pinAuditRoot(bytes32 root, uint256 count) external;
  ```
  The resulting on-chain transaction hash is stored back inside Atlas in `audit_ledger.anchor_tx_hash`.
  **The Punchline for Judges:** *"MongoDB Atlas provides high-throughput, private, sub-millisecond AI memory, while Hyperledger Besu provides immutable public cryptographic verification."*

#### 🌟 WOW Factor 5: Sub-5ms Change Stream Circuit Breaker (Mid-Run Kill Switch)
- **The Problem:** If an agent hallucinates or market conditions crash, operators need a deterministic, instantaneous kill switch that halts actions *before* they broadcast.
- **The MongoDB Solution:** An operator updating the shared `tenant_controls` record and incrementing its revision can notify workers through Change Streams. The serialized `SUBMISSION_PERMITTED` guard remains the authoritative stop boundary. An already permitted submission must be reconciled; a notification cannot retract a broadcast transaction. The worker subscription and latency target require implementation and measurement.

## 3. Required behavior and correctness

### Evidence-grounded analysis

Seed approximately 12–20 verified regulatory chunks, six fictional counterparties, and four historical cases across two tenants. Label fictional entities and outcomes as demo fixtures.

For every regulatory chunk, retain the source URL, document version, section, effective interval, text hash, and review status. Verify citations before ingestion: the current Singapore Act lists section 5 as licensing of payment service providers and section 6 as application for licence, correcting the worked example's section label. ([Payment Services Act](https://sso.agc.gov.sg/Act/PSA2019))

Use this retrieval path:

1. Resolve counterparties by exact normalized address and network.
2. Construct a factual transaction narrative.
3. Embed queries and documents using `voyage-finance-2`, which produces 1,024-dimensional vectors. ([Voyage reference](https://docs.voyageai.com/docs/embeddings))
4. Retrieve up to 20 candidates through Atlas `$vectorSearch`, with appropriate jurisdiction and governance filters.
5. Rerank through Voyage's API using `rerank-2.5`; retain three primary clauses and linked applicability or exception clauses.
6. Ask one configured language model for a validated finding containing cited chunk IDs, supporting facts, missing facts, and a concise explanation.

Keep the LLM provider/model configurable and record the exact model and prompt version with every finding. Reject citations outside the retrieved evidence set. Missing evidence, invalid output, or unavailable dependencies must lead to review rather than automatic execution.

Use explicit embeddings in the core. Atlas's documented automated-embedding model list does not include `voyage-finance-2`. Native `$rerank` is optional: capability-test it and use its documented `query.text`, `numDocsToRerank`, and subsequent `$limit` syntax. ([Automated-embedding models](https://www.mongodb.com/docs/vector-search/crud-embeddings/automated-embedding/models/), [reranking reference](https://www.mongodb.com/docs/vector-search/query/aggregation-stages/rerank/))

Present findings as **evidence-supported risk** or **review required**. A precedent match is an investigative lead; it cannot independently establish a legal violation. Display retrieval and reranking scores as relevance scores, without converting them into confidence percentages.

### Policy and approval

Support one external action in the core: **`HOLD_SETTLEMENT`**.

The default demo policy permits an automatic simulated hold only when:

- The target settlement belongs to the authenticated tenant.
- The action and target are allowlisted.
- Required evidence and analyst-confirmed precedent remain valid.
- The delegation permits the action.
- The proposed amount is at or below USD 250,000.

Larger amounts enter officer review. Invalid authority or prohibited targets are denied. Missing or contradictory evidence requires review and refreshed analysis before dispatch.

Bind approval to the immutable proposal digest, policy version, and evidence versions. A changed proposal requires a new decision. Revalidate authority, pause status, and evidence immediately before dispatch.

MongoDB schema validation checks document structure; application code verifies authority and policy semantics.

### Durable FSM and outbox

Use one canonical `ComplianceState`, advanced by a server-originated `ComplianceEvent`. The current leg is derived from state; shared waits retain a validated origin/resume checkpoint. Worker ownership, heartbeat, attempts, and due times are runtime metadata.

| Leg | Normal state progression | Required checkpoint |
|---|---|---|
| Intake | `RECEIVED → VALIDATING_CONTEXT → RESOLVING_PARTIES → RESOLVING_JURISDICTIONS → CONTEXT_READY` | Valid pending settlement, sourced party/jurisdiction facts, context digest |
| Evidence | `EMBEDDING_QUERY → SEARCHING_REGULATIONS → SEARCHING_PRECEDENTS → RERANKING_EVIDENCE → VALIDATING_EVIDENCE → EVIDENCE_READY` | Saved embedding, candidates, ranked clauses, authoritative evidence versions/digest |
| Analysis | `GENERATING_FINDING → VALIDATING_FINDING → FINDING_READY` | Validated cited finding, model and prompt version, input digest |
| Authorization | `EVALUATING_POLICY → AUTHORIZED`; review loop: `EVALUATING_POLICY → AWAITING_APPROVAL → EVALUATING_POLICY` | Exact proposal digest, current policy and authority, unique outbox intent |
| Dispatch | `PREPARING_ACTION → ACTION_PREPARED → SUBMITTING → SUBMITTED` or `SUBMISSION_UNKNOWN` | Prepared operation identity before send; serialized dispatch permit |
| Verification | `RECONCILING → VERIFYING_EFFECT → EFFECT_CONFIRMED → FINALIZING → FINALIZED`; pending loop: `RECONCILING ↔ AWAITING_EFFECT` | Successful receipt, observed hold, atomic final audit and historical case |

Every edge has a named event, allowed actor source, guard requirements, durable output requirements, and state-specific recovery semantics. The scaffold publishes these descriptions; it does not yet execute the guards or persist transitions. Replace generic `transition(next_state)` interfaces with `apply_event(fsm, event, lease)`.

Use `RETRY_WAIT` only for safe reads/computations or local finalization; default to three total attempts with two- and four-second waits. Use `AWAITING_INPUT` for correctable facts/evidence and `MANUAL_REVIEW` for unresolved external effects. Verification polls every second and moves to manual review after 120 seconds. `REJECTED`, `DENIED`, `ACTION_FAILED`, and `FINALIZED` are terminal. Pause remains separate from the business state.

A timeout or crash in `SUBMITTING` enters reconciliation using the stored operation. A `NOT_FOUND` response alone never authorizes replacement. A crash in `FINALIZING` retries only the local final record. Detailed per-leg tables and exception rules are maintained in the linked specification.

Implement these invariants:

- Lease acquisition increments a monotonic fencing token. Every workflow write checks the expected state, document version, lease owner, token, and unexpired lease.
- Use a ten-second lease, three-second heartbeat, and one-second recovery scan as initial demo defaults.
- Commit approval, the corresponding FSM transition, outbox insertion, and audit event in one MongoDB transaction.
- Keep external calls outside database transactions.
- Grant `SUBMISSION_PERMITTED` by checking the tenant control revision and conditionally writing that same record. Pause, policy changes, and relevant memory invalidation increment it, serializing governance changes with dispatch permission.
- Persist the prepared operation and stable idempotency key before dispatch.
- Enforce unique tenant-scoped request and action keys.
- On recovery, probe the saved operation before retrying. Never infer failure solely from a timeout.
- Automatically retry transient failures with bounded backoff. Ambiguous outcomes enter reconciliation; exhausted or unrecoverable failures enter manual review.

The simulator must atomically persist its operation identifier and hold effect, with a unique idempotency key. It must support delayed confirmation, response loss after success, rejection, and ambiguous probe results.

The core demonstrated guarantee is **retryable delivery with one simulator effect per action key**. A transactional outbox alone does not guarantee exactly-once behavior in arbitrary external systems. The EVM path must satisfy its durable preparation, downstream idempotency, and reconciliation requirements before extending that claim to live execution.

Completion requires a successful operation receipt **and** a probe showing the expected settlement is held. For the simulator, confirmation delays and loss are injected. For the EVM connector, completion requires an on-chain transaction receipt (`status == 0x1`), sufficient confirmations, the expected event, and a contract state assertion (`isSettlementHeld(settlementId) == true`). The indexer marks orphaned chain data; connecting those observations to FSM reconciliation remains runtime work. Releasing a protective hold remains a separate authorized action.

### Governed memory and audit

Enforce tenant, clearance, active status, effective dates, and analyst-review status during precedent retrieval. Recheck retrieved records against their authoritative documents before using them, including when search indexes lag behind updates.

Tombstone corrected precedents and link replacements. Preserve their historical versions for earlier decisions. Use TTL only for disposable context; expiration must be checked by the application because TTL deletion is asynchronous. ([TTL behavior](https://www.mongodb.com/docs/manual/core/index-ttl/))

For the memory demonstration, compare a saved case evaluation with and without one reviewed precedent. Record changed evidence and review outcomes as an **ablation comparison**, without claiming mathematical causal certainty.

Append a per-FSM audit event for each state transition, decision, invalidation, and connector outcome. Use canonical serialization, sequence numbers, previous hashes, and transactional appends. Provide verification and export commands. Describe the result as tamper-evident; external anchoring belongs on the roadmap.

### Pause and recovery semantics

The pause control prevents new dispatches after the worker observes it. Already dispatched operations continue to reconciliation.

Use durable polling as the core scheduling mechanism. Change Streams may improve responsiveness later, but must not become the only mechanism for discovering pending work. They require a replica set or sharded deployment. ([Change Streams documentation](https://www.mongodb.com/docs/manual/changestreams/))

Do not automatically release a protective hold when reporting or another downstream step fails. A release is a separate action requiring its own policy and approval.

## 4. Six-hour implementation sequence

| Window | Deliverable | Acceptance gate |
|---|---|---|
| **0:00–0:30** | Configuration, schemas, indexes, authentication, dependency preflight | Atlas transaction, vector query, Voyage embedding/reranking, and LLM smoke checks pass |
| **0:30–1:30** | Persistent simulator, six-leg FSM, fenced leases, outbox, audit appends | A manually seeded proposal reaches a verified hold |
| **1:30–2:30** | Curated corpus, retrieval, structured analyst finding | Evidence and precedent IDs are inspectable; unsupported citations are rejected |
| **2:30–3:30** | Policy gate, officer decisions, tenant filtering, invalidation | Automatic, review, denial, and invalidation paths pass |
| **3:30–4:30** | Recovery handling and failure injection | Worker death after external success produces one hold effect |
| **4:30–5:15** | Dashboard and evidence export | Operator can run, inspect, approve, pause, and revisit a case |
| **5:15–6:00** | Acceptance run, rehearsal, recording, setup documentation | Primary demo passes twice from a clean namespace |

Start database and search-index provisioning immediately. Required credentials or unavailable services are setup blockers; surface them in preflight rather than substituting unlabelled mocks.

The dashboard contains scenario controls, a simple sender-to-recipient graph, FSM timeline, finding and citation panel, precedent inspection, and action-verification details. Use saved server events to drive the display.

If behind schedule, remove graph animation and optional polish first. Preserve real retrieval, tenant isolation, authorization, durable execution, and crash recovery.

## 5. Validation, demo, and roadmap

### Required acceptance scenarios

1. **Automatic hold:** a USD 100,000 proposed settlement with qualifying evidence reaches one verified hold.
2. **Officer review:** a USD 1.6 million proposal remains undispatched until valid approval.
3. **Unauthorized request:** wrong tenant, role, target, or expired authority produces no external effect.
4. **Repeated submission:** the same request key returns the original FSM; conflicting content is rejected.
5. **Concurrent workers:** a stale lease holder cannot advance the FSM after another worker acquires it.
6. **Crash before dispatch:** the committed outbox resumes without repeating completed analysis.
7. **Lost response after success:** restart probes the saved operation and completes with one simulator effect.
8. **Memory governance:** another tenant's, expired, or invalidated precedent never authorizes an action.
9. **Dependency failure:** unavailable retrieval or malformed LLM output creates a reviewable failure without dispatch.
10. **Pause:** queued work stops; in-flight work remains visible and reconciles.
11. **Audit inspection:** modified, reordered, or missing internal records are detected; exported history matches the displayed FSM.

Use unit tests for policy and transitions, integration tests against a MongoDB replica set, and separate-process crash tests. Include one real Atlas/Voyage retrieval test and a dashboard smoke test.

### Three-minute demonstration

- **First minute:** analyze a proposed settlement; inspect its citations, precedent, and authorization.
- **Second minute:** inject response loss and kill the worker; restart and show the same operation reaching verified completion with one effect.
- **Final minute:** invalidate a precedent, run a fresh case, and show the changed review outcome and preserved historical record.

Measure latency and recovery time during rehearsal. Replace the original fixed timing and kill-switch claims with observed results.

### Ordered roadmap

1. **Live EVM & Besu Adapter (`SettlementHub.sol`):** Deploy a lightweight Solidity contract providing `freezeSettlement(bytes32,address,string)` and `pinAuditRoot(bytes32,uint256)`; verify canonical receipts, emitted contract events (`SettlementFrozen`, `AuditRootPinned`), and state assertion against the `EVMConnector` conformance test suite.
2. **Richer analyst workspace:** React Flow graph, streamed explanations, and draft compliance-report PDF export.
3. **Institutional custody integrations:** Fireblocks MPC quorum and reporting systems with documented idempotency and reconciliation behavior.
4. **Stronger operational boundaries:** separate service identities, signed delegated authority, transactional exposure reservations, and external audit-root anchoring.
5. **Advanced analysis:** independent challenge review and allowlisted schema migrations. Semantic similarity may suggest a migration; it cannot authorize changed execution payloads.

FireFly remains the architectural inspiration. The core does not depend on deploying Hyperledger FireFly.
