"""Unit tests for BlockchainIndexer, tenant isolation, and re-org resilience."""

from copy import deepcopy

import eth_abi
import pytest

from chainlex.blockchain.artifacts import (
    TOPIC_SETTLEMENT_FROZEN,
    TOPIC_SETTLEMENT_INITIATED,
)
from chainlex.blockchain.indexer import BlockchainIndexer, decode_log


class FakeCollection:
    def __init__(self):
        self.documents = {}

    async def find_one(self, query):
        for doc in self.documents.values():
            if all(doc.get(k) == v for k, v in query.items()):
                return deepcopy(doc)
        return None

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
                self.documents[doc_id] = deepcopy(doc)
        else:
            if "$set" in update:
                self.documents[match_id].update(deepcopy(update["$set"]))

    async def update_many(self, query, update):
        for doc in self.documents.values():
            match = True
            for k, v in query.items():
                if isinstance(v, dict) and "$gte" in v:
                    if doc.get(k, 0) < v["$gte"]:
                        match = False
                        break
                elif doc.get(k) != v:
                    match = False
                    break
            if match and "$set" in update:
                doc.update(deepcopy(update["$set"]))


class FakeDatabase:
    def __init__(self):
        self.chain_blocks = FakeCollection()
        self.chain_transactions = FakeCollection()
        self.contract_events = FakeCollection()


def test_decode_log_non_usd_currency():
    # Encode with non-USD currency: "EUR" and amount 25,000,000
    encoded_data = eth_abi.encode(["uint256", "string"], [25000000, "EUR"])
    log = {
        "topics": [
            TOPIC_SETTLEMENT_INITIATED,
            "0x" + "11" * 32,
            "0x" + "00" * 12 + "aa" * 20,
            "0x" + "00" * 12 + "bb" * 20,
        ],
        "data": "0x" + encoded_data.hex(),
    }
    decoded = decode_log(log)
    assert decoded is not None
    assert decoded["currency"] == "EUR"
    assert decoded["amount_minor"] == 25000000


def test_decode_log_settlement_frozen():
    encoded_reason = eth_abi.encode(["string"], ["Sanctions match"])
    log = {
        "topics": [
            TOPIC_SETTLEMENT_FROZEN,
            "0x" + "22" * 32,
            "0x" + "00" * 12 + "cc" * 20,
            "0x" + "00" * 12 + "dd" * 20,
        ],
        "data": "0x" + encoded_reason.hex(),
    }
    decoded = decode_log(log)
    assert decoded is not None
    assert decoded["event_name"] == "SettlementFrozen"
    assert decoded["reason"] == "Sanctions match"


@pytest.mark.asyncio
async def test_tenant_isolation_in_indexer():
    db = FakeDatabase()
    indexer_a = BlockchainIndexer(db, tenant_id="bank_a")
    indexer_b = BlockchainIndexer(db, tenant_id="bank_b")

    # Ingest block 1 for Tenant A
    b1_a = {"number": 1, "hash": "0xhash_a1", "parent_hash": "0x0", "timestamp": 100}
    await indexer_a.ingest_block(b1_a)

    # Ingest block 1 for Tenant B with different hash
    b1_b = {"number": 1, "hash": "0xhash_b1", "parent_hash": "0x0", "timestamp": 100}
    await indexer_b.ingest_block(b1_b)

    # Verify both records coexist and did not overwrite each other
    doc_a = await db.chain_blocks.find_one({"tenant_id": "bank_a", "block_number": 1})
    doc_b = await db.chain_blocks.find_one({"tenant_id": "bank_b", "block_number": 1})
    assert doc_a is not None and doc_a["block_hash"] == "0xhash_a1"
    assert doc_b is not None and doc_b["block_hash"] == "0xhash_b1"


@pytest.mark.asyncio
async def test_same_height_reorganization():
    db = FakeDatabase()
    indexer = BlockchainIndexer(db, tenant_id="bank_a")

    # Ingest block 2 (version A)
    b2_a = {"number": 2, "hash": "0xhash_A2", "parent_hash": "0xhash1", "timestamp": 200}
    tx_a = {"hash": "0xtx_A", "value_minor": 1000}
    await indexer.ingest_block(b2_a, transactions=[tx_a])

    doc_a = await db.chain_blocks.find_one({"tenant_id": "bank_a", "block_number": 2})
    assert doc_a["is_canonical"] is True

    # Same-height fork: incoming block 2 (version B) with different block hash
    b2_b = {"number": 2, "hash": "0xhash_B2", "parent_hash": "0xhash1", "timestamp": 205}
    res = await indexer.ingest_block(b2_b)

    assert res["reorg_detected"] is True
    assert res["reorg_block"] == 2

    # Check incoming is canonical and previous is updated
    updated_doc = await db.chain_blocks.find_one({"tenant_id": "bank_a", "block_number": 2})
    assert updated_doc["block_hash"] == "0xhash_B2"
    assert updated_doc["is_canonical"] is True
