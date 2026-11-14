"""End-to-End Blockchain & Mongo-Native Indexer Integration Test with receipt verification."""

import eth_abi
import httpx
import pytest

from chainlex.blockchain.artifacts import TOPIC_SETTLEMENT_FROZEN, TOPIC_SETTLEMENT_INITIATED
from chainlex.blockchain.event_bus import Web3EventBus
from chainlex.blockchain.indexer import BlockchainIndexer
from chainlex.blockchain.pinning import AuditPinService
from chainlex.blockchain.semantic_search import TransactionVectorizer
from chainlex.connectors.evm import EVMConnector, _to_bytes32
from chainlex.domain.models import HoldAction, ProbeOutcome


class FullFakeCollection:
    def __init__(self):
        self.documents = {}

    async def find_one(self, query):
        for doc in self.documents.values():
            if all(doc.get(k) == v for k, v in query.items()):
                return doc.copy()
        return None

    def find(self, query):
        filtered = []
        for doc in self.documents.values():
            if query.get("tenant_id") and doc.get("tenant_id") != query.get("tenant_id"):
                continue
            if "$or" in query:
                if doc.get("anchor_tx_hash") is None:
                    filtered.append(doc.copy())
            elif all(doc.get(k) == v for k, v in query.items() if not isinstance(v, dict)):
                filtered.append(doc.copy())

        class FakeCursor:
            def __init__(self, items):
                self.items = items

            def limit(self, n):
                return FakeCursor(self.items[:n])

            def __aiter__(self):
                self._iter = iter(self.items)
                return self

            async def __anext__(self):
                try:
                    return next(self._iter)
                except StopIteration as err:
                    raise StopAsyncIteration from err

        return FakeCursor(filtered)

    async def update_one(self, query, update, upsert=False):
        match_id = None
        for doc_id, doc in self.documents.items():
            if all(doc.get(k) == v for k, v in query.items()):
                match_id = doc_id
                break

        if match_id is None:
            if upsert:
                doc = query.copy()
                if "$set" in update:
                    doc.update(update["$set"])
                doc_id = doc.get("_id", f"doc_{len(self.documents)}")
                doc["_id"] = doc_id
                self.documents[doc_id] = doc.copy()
        else:
            if "$set" in update:
                self.documents[match_id].update(update["$set"].copy())

    async def update_many(self, query, update):
        target_ids = query.get("_id", {}).get("$in", [])
        for tid in target_ids:
            if tid in self.documents and "$set" in update:
                self.documents[tid].update(update["$set"].copy())


class FullFakeDatabase:
    def __init__(self):
        self.chain_blocks = FullFakeCollection()
        self.chain_transactions = FullFakeCollection()
        self.contract_events = FullFakeCollection()
        self.audit_ledger = FullFakeCollection()
        self.tx_outbox = FullFakeCollection()


@pytest.mark.asyncio
async def test_blockchain_lifecycle_end_to_end():
    db = FullFakeDatabase()
    settlement_id_b32 = _to_bytes32("settlement_e2e_01")
    contract_held = False

    def evm_rpc_handler(request: httpx.Request) -> httpx.Response:
        nonlocal contract_held
        import json

        body = json.loads(request.content)
        method = body.get("method")
        params = body.get("params", [])

        if method == "eth_sendTransaction":
            data = params[0].get("data", "")
            if data.startswith("0x1dd281a8"):
                contract_held = True
                return httpx.Response(
                    200, json={"jsonrpc": "2.0", "id": 1, "result": "0xtx_freeze_success"}
                )
            elif data.startswith("0x977db3e9"):
                return httpx.Response(
                    200, json={"jsonrpc": "2.0", "id": 1, "result": "0xtx_pin_success"}
                )
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0xtx_default"})
        elif method == "eth_blockNumber":
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "id": 1, "result": "0x6e"}
            )  # block 110
        elif method == "eth_getTransactionReceipt":
            tx_h = params[0]
            if tx_h == "0xtx_freeze_success":
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "status": "0x1",
                            "blockNumber": "0x64",  # block 100 (10 confirmations)
                            "logs": [{"topics": [TOPIC_SETTLEMENT_FROZEN, settlement_id_b32]}],
                        },
                    },
                )
            elif tx_h == "0xtx_pin_success":
                return httpx.Response(
                    200, json={"jsonrpc": "2.0", "id": 1, "result": {"status": "0x1"}}
                )
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": None})
        elif method == "eth_call":
            res_hex = (
                "0x0000000000000000000000000000000000000000000000000000000000000001"
                if contract_held
                else "0x0000000000000000000000000000000000000000000000000000000000000000"
            )
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": res_hex})
        return httpx.Response(404)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(evm_rpc_handler))
    connector = EVMConnector(
        rpc_url="http://mock-besu-node",
        contract_address="0xSettlementHub000000000000000000000001",
        client=mock_client,
        outbox_collection=db.tx_outbox,
        required_confirmations=2,
    )

    # 1. Ingest Block & SettlementInitiated Event via Indexer
    indexer = BlockchainIndexer(db, tenant_id="bank_a")
    block_data = {
        "number": 100,
        "hash": "0xblock100",
        "parent_hash": "0xblock99",
        "timestamp": 1700000000,
    }
    tx_data = [{"hash": "0xinitiate_tx", "from": "0xAlice", "to": "0xBob", "value_minor": 25000000}]
    encoded_init = eth_abi.encode(["uint256", "string"], [25000000, "USD"])
    log_data = [
        {
            "transactionHash": "0xinitiate_tx",
            "logIndex": 0,
            "address": "0xSettlementHub000000000000000000000001",
            "topics": [
                TOPIC_SETTLEMENT_INITIATED,
                settlement_id_b32,
                "0x" + "00" * 12 + "11" * 20,
                "0x" + "00" * 12 + "22" * 20,
            ],
            "data": "0x" + encoded_init.hex(),
        }
    ]
    index_res = await indexer.ingest_block(block_data, tx_data, log_data)
    assert index_res["event_count"] == 1

    # 2. Event Bus receives event
    pushed_events = []

    async def on_event(params):
        pushed_events.append(params)

    event_bus = Web3EventBus(db, on_settlement_initiated=on_event, tenant_id="bank_a")
    indexed_event = list(db.contract_events.documents.values())[0]
    await event_bus._handle_event(indexed_event)
    assert len(pushed_events) == 1
    assert pushed_events[0]["settlement_id"] == settlement_id_b32

    # 3. Agent decides to HOLD_SETTLEMENT
    action = HoldAction(
        tenant_id="bank_a", settlement_id="settlement_e2e_01", amount_minor=25000000
    )
    prepared = await connector.prepare(action, idempotency_key="hold_idem_100")

    # Dispatch freeze to smart contract
    dispatch_ref = await connector.dispatch(prepared)
    assert dispatch_ref.provider == "evm"
    assert dispatch_ref.tx_hash == "0xtx_freeze_success"

    # Probe on-chain state -> CONFIRMED
    probe_result = await connector.probe(prepared)
    assert probe_result.outcome == ProbeOutcome.CONFIRMED
    assert probe_result.effect == "HELD"

    # 4. Semantic Vectorization of on-chain tx
    vectorizer = TransactionVectorizer(db, tenant_id="bank_a")
    vector = [0.05] * 1024
    await vectorizer.vectorize_transaction("0xinitiate_tx", custom_vector=vector)
    stored_tx = await db.chain_transactions.find_one(
        {"tenant_id": "bank_a", "tx_hash": "0xinitiate_tx"}
    )
    assert stored_tx["embedding"] == vector

    # 5. Audit Anchoring / Pinning to Smart Contract
    await db.audit_ledger.update_one(
        {"_id": "audit_rec_001"},
        {"$set": {"tenant_id": "bank_a", "record_hash": "0x" + "fe" * 32}},
        upsert=True,
    )
    pin_service = AuditPinService(db, connector, tenant_id="bank_a")
    pin_res = await pin_service.pin_audit_batch(batch_size=10)
    assert pin_res is not None
    assert pin_res["status"] == "CONFIRMED"
    assert pin_res["anchor_tx_hash"] == "0xtx_pin_success"

    await connector.close()
