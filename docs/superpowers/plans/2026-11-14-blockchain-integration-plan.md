# ChainLex Blockchain Integration & Mongo-Native Indexer Implementation Plan

> **For agentic workers:** Execute this plan inline, task by task, adhering strictly to the architecture established in [chainlex_enriched_hackathon_plan.md](../../../chainlex_enriched_hackathon_plan.md) and the connector interface in `src/chainlex/connectors/base.py`.

**Goal:** Deliver a production-grade, end-to-end blockchain integration for ChainLex featuring:
1. The **`EVMConnector`** implementing the `SettlementConnector` protocol (`prepare`, `dispatch`, `probe`) for Hyperledger Besu / EVM testnets.
2. The **`SettlementHub.sol`** smart contract supporting simulated settlement flows, contract freezing, and Merkle audit root pinning.
3. The **Mongo-Native Blockchain Indexer** ingesting blocks, transactions, and ABI-decoded events into Atlas with re-org detection.
4. The **Change Stream Event Bus** pushing on-chain settlement events directly to the compliance workflow with $<10\text{ms}$ latency (zero polling).
5. The **On-Chain Audit Anchor** pinning cryptographic Merkle roots of Atlas audit records to the smart contract.
6. The **Semantic Blockchain Explorer** embedding decoded transactions with Voyage AI (`voyage-finance-2`) for natural language vector search in Atlas.

---

## Architecture Alignment

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        CHAINLEX BLOCKCHAIN INTEGRATION ARCHITECTURE                    │
├────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                        │
│   [Besu / EVM Node] <── (JSON-RPC) ──> [EVMConnector] (Conforms to SettlementConnector)│
│          │                                      │                                      │
│          ▼ (eth_getLogs & blocks)               ▼                                      │
│   ┌──────────────────────────────┐     ┌───────────────────────────────────────────┐   │
│   │   Mongo-Native Indexer       │     │   Transactional Outbox (`tx_outbox`)      │   │
│   │   - Re-org detection         │     │   - Raw signed EIP-1559 bytes             │   │
│   │   - ABI event decoder        │     │   - Sequential nonce management in Atlas  │   │
│   └──────────────┬───────────────┘     └─────────────────────┬─────────────────────┘   │
│                  │                                           │                         │
│                  ▼                                           ▼                         │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │                       MONGODB ATLAS OPERATIONAL STORE                          │   │
│   │   `chain_blocks` | `chain_transactions` | `contract_events` | `audit_ledger`   │   │
│   └──────────────────────┬───────────────────────────────────┬─────────────────────┘   │
│                          │                                   │                         │
│                          ▼ (Change Streams)                  ▼ (Atlas Vector Search)   │
│   ┌──────────────────────────────────────────┐   ┌─────────────────────────────────┐   │
│   │   Change Stream Web3 Event Bus           │   │   Semantic Blockchain Explorer  │   │
│   │   - Pushes `SettlementInitiated` events  │   │   - Natural language search     │   │
│   │     directly to compliance workflow      │   │     over raw on-chain txs       │   │
│   └──────────────────────────────────────────┘   └─────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Task 1: Smart Contract Design & ABI Artifacts
**Files:** `contracts/SettlementHub.sol`, `src/chainlex/blockchain/artifacts.py`

- [ ] Write `contracts/SettlementHub.sol`:
  - `event SettlementInitiated(bytes32 indexed settlementId, address indexed from, address indexed to, uint256 amountMinor, string currency);`
  - `event SettlementFrozen(bytes32 indexed settlementId, address indexed counterparty, string reason, address operator);`
  - `event AuditRootPinned(bytes32 indexed merkleRoot, uint256 batchCount, uint256 timestamp);`
  - `function freezeSettlement(bytes32 settlementId, address counterparty, string calldata reason) external;`
  - `function isSettlementHeld(bytes32 settlementId) external view returns (bool);`
  - `function pinAuditRoot(bytes32 root, uint256 batchCount) external;`
- [ ] Export compiled bytecode and full ABI in `src/chainlex/blockchain/artifacts.py`.
- [ ] Write deployment and local test fixture helper using `web3.py`.

---

## Task 2: EVMConnector Implementation (Matching SettlementConnector Protocol)
**Files:** `src/chainlex/connectors/evm.py`, `src/chainlex/domain/models.py`, `tests/test_evm_connector.py`

- [ ] Update `DispatchReference` in `src/chainlex/domain/models.py` to allow `provider: Literal["simulator", "evm"]`.
- [ ] Implement `EVMConnector` conforming to `SettlementConnector`:
  - **`prepare(action: HoldAction, idempotency_key: str) -> PreparedAction`**:
    - Validates action parameters and computes deterministic `operation_id` and `payload_digest`.
    - Encodes the ABI call for `freezeSettlement(settlementId, counterparty, reason)`.
    - Generates signed transaction bytes using the operator's private key and next sequential nonce.
  - **`dispatch(prepared_action: PreparedAction) -> DispatchReference`**:
    - Broadcasts `eth_sendRawTransaction(signed_bytes)`.
    - Records node submission and returns `DispatchReference(operation_id=operation_id, provider="evm")`.
  - **`probe(prepared_action: PreparedAction) -> ProbeResult`**:
    - Calls `eth_getTransactionReceipt(tx_hash)`.
    - If mined: checks `receipt.status == 1`, verifies block confirmations $\ge \text{required\_confirmations}$, and asserts contract state `isSettlementHeld(settlementId) == True`. Returns `ProbeOutcome.CONFIRMED` with `effect="HELD"`.
    - If `status == 0`: returns `ProbeOutcome.REVERTED`.
    - If in mempool / pending: returns `ProbeOutcome.PENDING`.
    - If missing after timeout: returns `ProbeOutcome.NOT_FOUND`.
- [ ] Write unit and conformance tests validating identical behavior to `SimulatorConnector`.

---

## Task 3: Mongo-Native Blockchain Indexer with Re-org Detection
**Files:** `src/chainlex/blockchain/indexer.py`, `src/chainlex/db/indexes.py`, `tests/test_indexer.py`

- [ ] Register new collections in `src/chainlex/db/indexes.py`:
  - `chain_blocks`: `{ block_number: 1 (unique), block_hash: 1, parent_hash: 1, timestamp: 1 }`
  - `chain_transactions`: `{ tx_hash: 1 (unique), from: 1, to: 1, block_number: 1 }`
  - `contract_events`: `{ tx_hash: 1, log_index: 1, event_name: 1, is_orphaned: 1 }`
- [ ] Implement `BlockchainIndexer`:
  - `poll_latest_blocks(from_block, to_block)`: fetches blocks and transaction receipts.
  - **Re-org Detection:** Verifies `parent_hash == previous_block_hash`. If a fork is detected, marks `is_orphaned: True` on orphaned events and blocks atomically.
  - **ABI Event Decoder:** Decodes raw Ethereum logs into typed JSON documents (`SettlementInitiated`, `SettlementFrozen`, `AuditRootPinned`).

---

## Task 4: Reactive Web3 Event Bus (Atlas Change Streams)
**Files:** `src/chainlex/blockchain/event_bus.py`, `src/chainlex/worker/main.py`

- [ ] Implement `EventBusListener`:
  - Opens an async Change Stream on `contract_events` filtered on `operationType: "insert"` and `event_name: "SettlementInitiated"`.
  - On event received: extracts `settlementId`, `from`, `to`, `amountMinor`, and automatically queues a `CreateJob` workflow into `job_executions` in $<10\text{ms}$.
  - Provides graceful fallback to checkpoint polling if Change Streams are unavailable (e.g. standalone Mongo during local development).

---

## Task 5: Hyperledger FireFly-Style State Pinning & Merkle Anchoring
**Files:** `src/chainlex/blockchain/pinning.py`, `tests/test_pinning.py`

- [ ] Implement `AuditPinService`:
  - Reads unpinned entries from `audit_ledger` (where `anchor_tx_hash is None`).
  - Computes the cryptographic Merkle Root over the SHA-256 record hashes:
    $$\text{Root} = \text{MerkleTree}(\{ \text{record.record\_hash} \})$$
  - Dispatches `SettlementHub.pinAuditRoot(merkleRoot, batchCount)` via `EVMConnector`.
  - Updates the batched `audit_ledger` documents with `{ anchor_tx_hash: tx_hash, pinned_at: datetime.utcnow() }`.

---

## Task 6: Semantic Blockchain Search (Voyage AI + Atlas Vector Search)
**Files:** `src/chainlex/blockchain/semantic_search.py`, `src/chainlex/db/vector_indexes.json`

- [ ] Register vector search index for `chain_transactions` in `vector_indexes.json`:
  - Index `embedding` (1,024 dimensions, `voyage-finance-2`, cosine similarity).
  - Filter fields: `from`, `to`, `status`, `block_number`.
- [ ] Implement `TransactionVectorizer`:
  - Formats transaction into structured narrative: *"Transfer of 150,000 USD from 0xSender to 0xRecipient on Besu network. Interacted with SettlementHub."*
  - Embeds narrative via Voyage AI and saves to `chain_transactions.embedding`.
- [ ] Expose semantic search query helper:
  - `search_transactions_natural_language(query: str, limit: int = 10) -> list[Transaction]`.

---

## Task 7: End-to-End Integration & Demo Script
**Files:** `tests/test_blockchain_e2e.py`, `docs/blockchain-demo-guide.md`

- [ ] Build end-to-end integration test:
  1. Emit `SettlementInitiated` event on local test chain.
  2. Indexer ingests log $\rightarrow$ Change Stream pushes to Agent.
  3. Agent analyzes risk $\rightarrow$ Policy gate approves hold.
  4. `EVMConnector` dispatches `freezeSettlement` $\rightarrow$ Receipt confirmed on-chain.
  5. Audit root pinned to contract $\rightarrow$ State verified in Atlas.
- [ ] Document live demo execution commands for stage presentation.

