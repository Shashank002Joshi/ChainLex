"""Unit tests for Merkle root computation and on-chain audit pinning."""

import httpx
import pytest

from chainlex.blockchain.pinning import AuditPinService, compute_merkle_root
from chainlex.connectors.evm import EVMConnector


class FakeAuditCollection:
    def __init__(self, records):
        self.records = {r["_id"]: r for r in records}

    def find(self, query):
        filtered = [
            r for r in self.records.values()
            if r.get("tenant_id") == query.get("tenant_id")
            and r.get("anchor_tx_hash") is None
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
                except StopIteration:
                    raise StopAsyncIteration

        return FakeCursor(filtered)

    async def update_many(self, query, update):
        target_ids = query.get("_id", {}).get("$in", [])
        for tid in target_ids:
            if tid in self.records and "$set" in update:
                self.records[tid].update(update["$set"])


class FakePinningDb:
    def __init__(self, audit_records):
        self.audit_ledger = FakeAuditCollection(audit_records)


def test_compute_merkle_root():
    h1 = "0x" + "aa" * 32
    h2 = "0x" + "bb" * 32
    h3 = "0x" + "cc" * 32

    root1 = compute_merkle_root([h1])
    assert root1 == h1

    root2 = compute_merkle_root([h1, h2])
    assert root2.startswith("0x")
    assert len(root2) == 66
    assert root2 != h1 and root2 != h2

    # Determinism check
    root_odd = compute_merkle_root([h1, h2, h3])
    root_odd_again = compute_merkle_root([h1, h2, h3])
    assert root_odd == root_odd_again


@pytest.mark.asyncio
async def test_audit_pin_service():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0xanchortx777"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = EVMConnector(
        rpc_url="http://mock-rpc",
        contract_address="0x1111111111111111111111111111111111111111",
        client=client,
    )

    initial_records = [
        {"_id": "rec_1", "tenant_id": "bank_a", "record_hash": "0x1111111111111111111111111111111111111111111111111111111111111111"},
        {"_id": "rec_2", "tenant_id": "bank_a", "record_hash": "0x2222222222222222222222222222222222222222222222222222222222222222"},
    ]
    db = FakePinningDb(initial_records)
    service = AuditPinService(db, connector, tenant_id="bank_a")

    res = await service.pin_audit_batch(batch_size=10)
    assert res is not None
    assert res["batch_count"] == 2
    assert res["anchor_tx_hash"] == "0xanchortx777"
    assert res["merkle_root"].startswith("0x")

    # Verify audit records in DB were updated with anchor proof
    assert db.audit_ledger.records["rec_1"]["anchor_tx_hash"] == "0xanchortx777"
    assert db.audit_ledger.records["rec_2"]["anchor_tx_hash"] == "0xanchortx777"

    await connector.close()
