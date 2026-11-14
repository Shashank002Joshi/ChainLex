"""Unit tests for semantic transaction search and pipeline generation."""

import pytest

from chainlex.blockchain.semantic_search import TransactionVectorizer, format_tx_narrative


class FakeTxCollection:
    def __init__(self, txs):
        self.txs = {t["tx_hash"]: t for t in txs}

    async def find_one(self, query):
        return self.txs.get(query.get("tx_hash"))

    async def update_one(self, query, update):
        tx = self.txs.get(query.get("tx_hash"))
        if tx and "$set" in update:
            tx.update(update["$set"])


class FakeTxDb:
    def __init__(self, txs):
        self.chain_transactions = FakeTxCollection(txs)


def test_format_tx_narrative():
    tx = {
        "from": "0xAlice",
        "to": "0xBob",
        "value_minor": 15000000,
        "currency": "USD",
        "block_number": 4201,
        "status": 1,
        "memo": "Payment for software licensing",
    }
    narrative = format_tx_narrative(tx)
    assert "150000.00 USD" in narrative
    assert "0xAlice" in narrative
    assert "0xBob" in narrative
    assert "block height 4201" in narrative
    assert "Payment for software licensing" in narrative


@pytest.mark.asyncio
async def test_vectorize_transaction_and_pipeline():
    tx = {
        "tx_hash": "0xtx99",
        "from": "0x111",
        "to": "0x222",
        "value_minor": 500000,
        "currency": "USD",
        "block_number": 100,
        "status": 1,
    }
    db = FakeTxDb([tx])
    vectorizer = TransactionVectorizer(db, tenant_id="bank_a")

    dummy_vector = [0.1] * 1024
    saved = await vectorizer.vectorize_transaction("0xtx99", custom_vector=dummy_vector)
    assert saved == dummy_vector
    assert db.chain_transactions.txs["0xtx99"]["embedding"] == dummy_vector
    assert "narrative" in db.chain_transactions.txs["0xtx99"]

    # Test pipeline generator
    pipeline = vectorizer.build_vector_search_pipeline(query_vector=dummy_vector, limit=5)
    assert len(pipeline) == 2
    assert "$vectorSearch" in pipeline[0]
    v_search = pipeline[0]["$vectorSearch"]
    assert v_search["index"] == "chain_transactions_idx"
    assert v_search["limit"] == 5
    assert v_search["filter"]["$and"][0]["tenant_id"]["$eq"] == "bank_a"
