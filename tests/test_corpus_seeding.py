from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from chainlex.config import Settings
from chainlex.db.corpus_seeding import seed_latest
from chainlex.services.country_corpus import default_corpus_directory, load_bank_corpus, load_corpus
from chainlex.services.country_rules import ingest_policies, ingest_rules


class Collection:
    def __init__(self):
        self.documents = {}

    async def find_one(self, query):
        doc = self.documents.get(query["_id"])
        return deepcopy(doc) if doc and all(doc.get(k) == v for k, v in query.items()) else None

    async def update_one(self, query, update, **kwargs):
        inserted = query["_id"] not in self.documents
        if inserted:
            self.documents[query["_id"]] = deepcopy(update["$setOnInsert"])
        return SimpleNamespace(upserted_id=query["_id"] if inserted else None)


class Database:
    def __init__(self):
        self.collections = {
            name: Collection()
            for name in ("entities", "compliance_cases", "policies", "regulations")
        }

    def __getitem__(self, name):
        return self.collections[name]

    def __getattr__(self, name):
        return self.collections[name]


def test_default_corpus_does_not_depend_on_current_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    directory = default_corpus_directory()
    rules, policies = load_corpus(directory)
    assert len(rules) == len(policies) == 12
    assert len(load_bank_corpus(directory)) == 3


async def test_no_key_seeds_policies_without_any_regulation_or_provider_calls(monkeypatch):
    db = Database()
    monkeypatch.setattr(
        "chainlex.db.corpus_seeding.VoyageEmbeddings",
        lambda *args: pytest.fail("No key: no provider client"),
    )
    result = await seed_latest(db, Settings(_env_file=None))
    assert len(db.entities.documents) == 6
    assert len(db.compliance_cases.documents) == 4
    assert len(db.policies.documents) == 15
    assert not db.regulations.documents
    assert result["policies"]["inserted"] == 15
    assert result["regulations"]["status"] == "skipped"
    assert result["regulations"]["reason"] == "CHAINLEX_VOYAGE_API_KEY_NOT_CONFIGURED"
    assert result["regulations"]["available"] == 12
    assert all(
        not doc["is_active"] and doc["review_status"] == "UNVERIFIED"
        for doc in db.policies.documents.values()
    )


async def test_repeat_seed_preserves_review_and_tenant_isolation():
    db = Database()
    await seed_latest(db, Settings(_env_file=None))
    existing = next(iter(db.policies.documents.values()))
    existing.update(
        {"review_status": "VERIFIED", "is_active": True, "review_note": "Officer decision"}
    )
    before = deepcopy(existing)
    result = await seed_latest(db, Settings(_env_file=None))
    assert result["policies"]["inserted"] == 0
    assert result["policies"]["existing_preserved"] == 15
    assert existing == before
    await seed_latest(db, Settings(_env_file=None, demo_tenant_id="bank_b"))
    assert len(db.policies.documents) == 30
    assert {doc["tenant_id"] for doc in db.policies.documents.values()} == {"bank_a", "bank_b"}


async def test_provider_failure_does_not_block_policies_or_store_unembedded_rules(monkeypatch):
    db = Database()
    request = httpx.Request("POST", "https://ai.mongodb.com/v1/embeddings")
    error = httpx.HTTPStatusError(
        "Provider unavailable", request=request, response=httpx.Response(503, request=request)
    )
    voyage = SimpleNamespace(embed=AsyncMock(side_effect=error))
    monkeypatch.setattr("chainlex.db.corpus_seeding.VoyageEmbeddings", lambda *args: voyage)
    with pytest.raises(httpx.HTTPStatusError):
        await seed_latest(db, Settings(_env_file=None, voyage_api_key="test-only-key"))
    assert len(db.policies.documents) == 15
    assert not db.regulations.documents


async def test_configured_key_stores_valid_embeddings_and_skips_existing(monkeypatch):
    db = Database()
    voyage = SimpleNamespace(embed=AsyncMock(return_value=[[0.1] * 1024 for _ in range(12)]))
    monkeypatch.setattr("chainlex.db.corpus_seeding.VoyageEmbeddings", lambda *args: voyage)
    settings = Settings(_env_file=None, voyage_api_key="test-only-key")
    result = await seed_latest(db, settings)
    assert result["regulations"]["status"] == "complete"
    assert result["regulations"]["inserted"] == 12
    assert len(db.regulations.documents) == 12
    document = next(iter(db.regulations.documents.values()))
    document["review_status"] = "VERIFIED"
    result = await seed_latest(db, settings)
    assert result["regulations"]["existing_preserved"] == 12
    assert voyage.embed.await_count == 1
    assert document["review_status"] == "VERIFIED"


@pytest.mark.parametrize("vectors", [[[0.1] * 1024, [0.1] * 3], [[0.1] * 1024]])
async def test_all_vectors_validate_before_any_regulation_write(vectors):
    db = Database()
    rules, _ = load_corpus(default_corpus_directory())
    voyage = SimpleNamespace(embed=AsyncMock(return_value=vectors))
    with pytest.raises(ValueError):
        await ingest_rules(db, voyage, rules[:2], "bank_a")
    assert not db.regulations.documents


async def test_policy_id_collisions_are_rejected_before_writes():
    db = Database()
    _, policies = load_corpus(default_corpus_directory())
    with pytest.raises(ValueError, match="Duplicate"):
        await ingest_policies(db, [policies[0], policies[0]], "bank_a")
    assert not db.policies.documents


async def test_seed_uses_configured_voyage_endpoint(monkeypatch):
    db = Database()
    calls = []
    voyage = SimpleNamespace(embed=AsyncMock(return_value=[[0.1] * 1024 for _ in range(12)]))

    def create_provider(http, key, endpoint):
        calls.append(endpoint)
        return voyage

    monkeypatch.setattr("chainlex.db.corpus_seeding.VoyageEmbeddings", create_provider)
    await seed_latest(
        db,
        Settings(
            _env_file=None,
            voyage_api_key="test-only-key",
            embedding_endpoint="https://api.voyageai.com/v1/embeddings",
        ),
    )
    assert calls == ["https://api.voyageai.com/v1/embeddings"]
    assert len(db.regulations.documents) == 12
