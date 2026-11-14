import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from chainlex.blockchain.semantic_search import TransactionVectorizer
from chainlex.services.country_cli import load_corpus
from chainlex.services.country_rules import ingest_rules
from chainlex.services.embeddings import VoyageEmbeddings


@pytest.mark.parametrize("input_type", ["document", "query"])
async def test_shared_transport_orders_results_and_preserves_input_type(input_type):
    def handler(request):
        payload = json.loads(request.content)
        assert payload["input_type"] == input_type
        assert payload["model"] == "voyage-finance-2"
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.2] * 1024},
                    {"index": 0, "embedding": [0.1] * 1024},
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await VoyageEmbeddings(http, "test-key").embed(["first", "second"], input_type)
    assert [row[0] for row in result] == [0.1, 0.2]


@pytest.mark.parametrize(
    "data",
    [
        [{"index": 0, "embedding": [0.1] * 3}],
        [{"index": 0, "embedding": [True] * 1024}],
        [{"index": 1, "embedding": [0.1] * 1024}],
        [],
    ],
)
async def test_shared_transport_rejects_invalid_response(data):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": data}))
    ) as http:
        with pytest.raises(ValueError):
            await VoyageEmbeddings(http, "test-key").embed(["rule"], "document")


async def test_regulation_reimport_skips_api_preserves_review_and_embeds_changes():
    stored = {}

    async def find_one(query):
        return stored.get(query["_id"])

    async def update_one(query, update, **kwargs):
        stored.setdefault(query["_id"], update["$setOnInsert"])

    db = SimpleNamespace(regulations=SimpleNamespace(find_one=find_one, update_one=update_one))
    voyage = SimpleNamespace(embed=AsyncMock(return_value=[[0.1] * 1024]))
    rule = load_corpus(Path("data/country_rules"))[0][0]
    await ingest_rules(db, voyage, [rule], "bank_a")
    first = next(iter(stored.values()))
    first["review_status"] = "VERIFIED"
    first["is_active"] = False
    await ingest_rules(db, voyage, [rule], "bank_a")
    assert voyage.embed.await_count == 1
    assert first["review_status"] == "VERIFIED" and not first["is_active"]
    changed = rule.model_copy(update={"rule_text": rule.rule_text + " Updated guidance."})
    await ingest_rules(db, voyage, [changed], "bank_a")
    assert voyage.embed.await_count == 2 and len(stored) == 2
    await ingest_rules(db, voyage, [rule], "bank_b")
    assert voyage.embed.await_count == 3 and len(stored) == 3


async def test_transaction_uses_shared_http_client_and_reembeds_only_when_changed():
    tx = {"tx_hash": "tx1", "tenant_id": "bank_a", "value_minor": 50000}
    requests = []

    async def find_one(query):
        assert query["tenant_id"] == "bank_a"
        return tx

    async def update_one(query, update):
        tx.update(update["$set"])

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * 1024}]})

    db = SimpleNamespace(
        chain_transactions=SimpleNamespace(
            find_one=find_one,
            update_one=update_one,
        )
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        vectorizer = TransactionVectorizer(db, VoyageEmbeddings(http, "test-key"))
        await vectorizer.vectorize_transaction("tx1")
        await vectorizer.vectorize_transaction("tx1")
        assert len(requests) == 1
        tx["memo"] = "New transaction details"
        await vectorizer.vectorize_transaction("tx1")
    assert len(requests) == 2
    assert all(request["input_type"] == "document" for request in requests)
    assert tx["embedding_model"] == "voyage-finance-2"


async def test_failed_provider_request_does_not_write_transaction():
    writes = AsyncMock()
    db = SimpleNamespace(
        chain_transactions=SimpleNamespace(
            find_one=AsyncMock(return_value={"tx_hash": "tx1"}),
            update_one=writes,
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(429))
    ) as http:
        vectorizer = TransactionVectorizer(db, VoyageEmbeddings(http, "test-key"))
        with pytest.raises(httpx.HTTPStatusError):
            await vectorizer.vectorize_transaction("tx1")
    writes.assert_not_awaited()
