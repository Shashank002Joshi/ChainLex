from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from chainlex.services.country_cli import load_corpus
from chainlex.services.country_rules import (
    CaseFacts,
    VoyageEmbeddings,
    evaluate_policies,
    ingest_rules,
    retrieval_pipeline,
)


async def test_ingestion_document_embedding_and_mongodb_shape():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    rules, _ = load_corpus(Path("data/country_rules"))
    voyage = SimpleNamespace(embed=AsyncMock(return_value=[[0.1] * 1024]))
    collection = SimpleNamespace(update_one=AsyncMock())
    db = SimpleNamespace(regulations=collection)
    rule = rules[0].model_copy(update={"valid_from": datetime(2025, 1, 1, tzinfo=UTC)})
    await ingest_rules(db, voyage, [rule], "bank_a")
    voyage.embed.assert_awaited_once_with([rule.embedding_text()], "document")
    args, kwargs = collection.update_one.call_args
    document = args[1]["$setOnInsert"]
    assert document["tenant_id"] == "bank_a"
    assert document["schema_version"] == 1
    assert document["review_status"] == "UNVERIFIED"
    assert document["embedding_model"] == "voyage-finance-2"
    assert len(document["embedding"]) == 1024
    assert isinstance(document["valid_from"], datetime)
    assert document["source_url"].startswith("https://")
    assert kwargs == {"upsert": True}


def test_corpus_and_policy_unknown_false_true():
    rules, policies = load_corpus(Path("data/country_rules"))
    assert {r.jurisdiction for r in rules} == {"SG", "CA", "US"}
    assert len(rules) == len(policies) == 12
    for country, fact in [
        ("SG", "cdd_complete"),
        ("CA", "travel_rule_complete"),
        ("US", "sanctions_clear"),
    ]:
        for value, outcome in [(None, "REVIEW"), (False, "REVIEW"), (True, "NO_MATCH")]:
            case = CaseFacts(
                jurisdictions=(country,),
                entity_type="MSB",
                transaction_type="VC_TRANSFER",
                narrative="Incoming transfer",
                **{fact: value},
            )
            result = evaluate_policies(case, [p for p in policies if p.required_fact == fact])
            assert result["outcome"] == outcome
            assert all(m["policy_id"].startswith(country) for m in result["matches"])


def test_all_enriched_policy_facts_and_regulations_only():
    rules, policies = load_corpus(Path("data/country_rules"))
    for policy in policies:
        for value, expected in [(None, "REVIEW"), (False, "REVIEW"), (True, "NO_MATCH")]:
            case = CaseFacts(
                jurisdictions=(policy.jurisdiction,),
                entity_type="DEMO",
                transaction_type="VC_TRANSFER",
                narrative="Review control evidence",
                **{policy.required_fact: value},
            )
            assert evaluate_policies(case, [policy])["outcome"] == expected
    assert all(r.topics and r.example_query and r.applicability_notes for r in rules)
    assert load_corpus(Path("data/country_rules"), regulations_only=True)[1] == []


def test_governed_pipeline():
    case = CaseFacts(
        jurisdictions=("CA", "SG"),
        entity_type="MSB",
        transaction_type="VC_TRANSFER",
        narrative="Missing transfer information",
    )
    now = datetime.now(UTC)
    pipeline = retrieval_pipeline(case, [0.1] * 1024, "bank_b", 2, now)
    filters = pipeline[0]["$vectorSearch"]["filter"]["$and"]
    assert {"tenant_id": {"$eq": "bank_b"}} in filters
    assert {"review_status": {"$eq": "VERIFIED"}} in filters
    assert {"jurisdiction": {"$in": ["CA", "SG"]}} in filters
    assert {"is_active": {"$eq": True}} in filters
    assert {"valid_from": {"$lte": now}} in filters
    assert {"clearance_level": {"$lte": 2}} in filters
    assert "$or" in filters[-1]


@pytest.mark.parametrize("dimension", [1024, 3])
async def test_voyage_request_and_dimension_validation(dimension):
    import json

    def handler(request):
        body = json.loads(request.content)
        assert body["input_type"] == "document"
        assert body["model"] == "voyage-finance-2"
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * dimension}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        voyage = VoyageEmbeddings(http, "test-key")
        if dimension == 1024:
            assert len((await voyage.embed(["rule"], "document"))[0]) == 1024
        else:
            with pytest.raises(ValueError, match="1024"):
                await voyage.embed(["rule"], "document")
