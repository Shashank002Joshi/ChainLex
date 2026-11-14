"""Unit tests for Merkle root computation and receipt-verified on-chain audit pinning."""

import httpx
import pytest

from chainlex.blockchain.pinning import (
    AuditPinService,
    canonical_document_hash,
    compute_merkle_root,
)
from chainlex.connectors.evm import EVMConnector


class FakeAuditCollection:
    def __init__(self, records):
        self.records = {r["_id"]: r.copy() for r in records}

    def find(self, query):
        filtered = [
            r
            for r in self.records.values()
            if r.get("tenant_id") == query.get("tenant_id") and r.get("anchor_tx_hash") is None
        ]

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

    async def update_many(self, query, update):
        target_ids = query.get("_id", {}).get("$in", [])
        for tid in target_ids:
            if tid in self.records and "$set" in update:
                self.records[tid].update(update["$set"])


class FakePinningDb:
    def __init__(self, audit_records):
        self.audit_ledger = FakeAuditCollection(audit_records)


def test_canonical_document_hash_detects_content_changes():
    doc1 = {"_id": "rec_1", "action": "HOLD", "amount": 100}
    doc2 = {"_id": "rec_1", "action": "HOLD", "amount": 200}  # changed content
    h1 = canonical_document_hash(doc1)
    h2 = canonical_document_hash(doc2)
    assert h1 != h2

    # Preserves equality regardless of key order
    doc1_reordered = {"amount": 100, "_id": "rec_1", "action": "HOLD"}
    assert canonical_document_hash(doc1_reordered) == h1


def test_compute_merkle_root():
    h1 = "0x" + "aa" * 32
    h2 = "0x" + "bb" * 32
    root = compute_merkle_root([h1, h2])
    assert root.startswith("0x")
    assert len(root) == 66


@pytest.mark.asyncio
async def test_audit_pin_unmined_stays_pending():
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        method = body.get("method")
        if method == "eth_sendTransaction":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0xunmined_tx"})
        elif method == "eth_getTransactionReceipt":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": None})
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = EVMConnector(
        rpc_url="http://mock-rpc",
        contract_address="0x1111111111111111111111111111111111111111",
        client=client,
    )
    db = FakePinningDb([{"_id": "rec_1", "tenant_id": "bank_a", "content": "test"}])
    service = AuditPinService(db, connector, tenant_id="bank_a")

    res = await service.pin_audit_batch(batch_size=10)
    assert res is not None
    assert res["status"] == "PENDING"
    # Document must NOT be marked as anchored in database
    assert db.audit_ledger.records["rec_1"].get("anchor_tx_hash") is None
    await connector.close()


@pytest.mark.asyncio
async def test_audit_pin_confirmed_receipt_anchors():
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        method = body.get("method")
        if method == "eth_sendTransaction":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0xmined_tx"})
        elif method == "eth_getTransactionReceipt":
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "id": 1, "result": {"status": "0x1"}}
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = EVMConnector(
        rpc_url="http://mock-rpc",
        contract_address="0x1111111111111111111111111111111111111111",
        client=client,
    )
    db = FakePinningDb([{"_id": "rec_1", "tenant_id": "bank_a", "content": "test"}])
    service = AuditPinService(db, connector, tenant_id="bank_a")

    res = await service.pin_audit_batch(batch_size=10)
    assert res is not None
    assert res["status"] == "CONFIRMED"
    assert db.audit_ledger.records["rec_1"]["anchor_tx_hash"] == "0xmined_tx"
    await connector.close()
