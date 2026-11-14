"""Unit tests for BlockchainIndexer and ABI decoding."""

from copy import deepcopy

import pytest

from chainlex.blockchain.artifacts import (
    TOPIC_AUDIT_ROOT_PINNED,
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
        # find matching doc or create new
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


def test_decode_log_settlement_initiated():
    log = {
        "topics": [
            TOPIC_SETTLEMENT_INITIATED,
            "0x" + "11" * 32,  # settlementId
            "0x" + "00" * 12 + "aa" * 20,  # from
            "0x" + "00" * 12 + "bb" * 20,  # to
        ],
        "data": "0x" + f"{10000000:064x}",
    }
    decoded = decode_log(log)
    assert decoded is not None
    assert decoded["event_name"] == "SettlementInitiated"
    assert decoded["settlement_id"] == "0x" + "11" * 32
    assert decoded["from_address"] == "0x" + "aa" * 20
    assert decoded["to_address"] == "0x" + "bb" * 20
    assert decoded["amount_minor"] == 10000000


def test_decode_log_settlement_frozen():
    log = {
        "topics": [
            TOPIC_SETTLEMENT_FROZEN,
            "0x" + "22" * 32,
            "0x" + "00" * 12 + "cc" * 20,
            "0x" + "00" * 12 + "dd" * 20,
        ],
        "data": "0x",
    }
    decoded = decode_log(log)
    assert decoded is not None
    assert decoded["event_name"] == "SettlementFrozen"
    assert decoded["settlement_id"] == "0x" + "22" * 32
    assert decoded["counterparty"] == "0x" + "cc" * 20
    assert decoded["operator"] == "0x" + "dd" * 20


@pytest.mark.asyncio
async def test_indexer_ingest_block_and_reorg():
    db = FakeDatabase()
    indexer = BlockchainIndexer(db, tenant_id="bank_a")

    # Ingest block 0 (genesis)
    b0 = {"number": 0, "hash": "0xhash0", "parent_hash": "0x0", "timestamp": 1000}
    res0 = await indexer.ingest_block(b0)
    assert res0["block_number"] == 0
    assert not res0["reorg_detected"]

    # Ingest block 1
    b1 = {"number": 1, "hash": "0xhash1", "parent_hash": "0xhash0", "timestamp": 1012}
    tx1 = {"hash": "0xtx1", "from": "0xaaa", "to": "0xbbb", "value_minor": 5000}
    log1 = {
        "transactionHash": "0xtx1",
        "logIndex": 0,
        "address": "0xcontract",
        "topics": [TOPIC_SETTLEMENT_INITIATED, "0x" + "33" * 32, "0x" + "00" * 12 + "aa" * 20, "0x" + "00" * 12 + "bb" * 20],
        "data": "0x" + f"{5000:064x}",
    }
    res1 = await indexer.ingest_block(b1, [tx1], [log1])
    assert res1["block_number"] == 1
    assert not res1["reorg_detected"]
    assert len(db.chain_transactions.documents) == 1
    assert len(db.contract_events.documents) == 1

    # Ingest alternative block 1 (fork/reorg with different hash)
    # Block 2 pointing to a fork parent instead of 0xhash1
    b2_fork = {"number": 2, "hash": "0xfork2", "parent_hash": "0xDIFFERENT_HASH", "timestamp": 1024}
    res2 = await indexer.ingest_block(b2_fork)
    assert res2["reorg_detected"] is True
    assert res2["reorg_block"] == 1

    # Verify that previously ingested records are marked orphaned
    b1_stored = await db.chain_blocks.find_one({"block_number": 1})
    assert b1_stored["is_orphaned"] is True
    assert b1_stored["is_canonical"] is False
