import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pymongo import AsyncMongoClient

from chainlex.config import Settings
from chainlex.db.corpus_seeding import seed_latest
from chainlex.db.indexes import bootstrap

pytestmark = pytest.mark.integration


async def test_policy_and_embedded_regulation_seed_is_additive(monkeypatch):
    uri = os.environ.get("CHAINLEX_TEST_MONGODB_URI")
    if not uri:
        pytest.skip("Set CHAINLEX_TEST_MONGODB_URI for a disposable MongoDB database")
    client = AsyncMongoClient(uri, serverSelectionTimeoutMS=5000, tz_aware=True)
    name = "chainlex_test_corpus_" + uuid4().hex
    db = client[name]
    try:
        await bootstrap(db)
        settings = Settings(_env_file=None, database=name, voyage_api_key="")
        first = await seed_latest(db, settings)
        assert first["policies"]["inserted"] == 15
        assert first["regulations"]["status"] == "skipped"
        assert await db.regulations.count_documents({}) == 0
        assert await db.entities.count_documents({}) == 6
        assert await db.compliance_cases.count_documents({}) == 4

        policy = await db.policies.find_one({"tenant_id": "bank_a"})
        await db.policies.update_one(
            {"_id": policy["_id"]},
            {
                "$set": {
                    "review_status": "VERIFIED",
                    "is_active": True,
                    "officer_note": "Preserve review",
                }
            },
        )
        second = await seed_latest(db, settings)
        assert second["policies"]["inserted"] == 0
        assert second["policies"]["existing_preserved"] == 15
        reviewed = await db.policies.find_one({"_id": policy["_id"]})
        assert reviewed["review_status"] == "VERIFIED" and reviewed["is_active"]
        assert reviewed["officer_note"] == "Preserve review"

        # Mock only provider transport; MongoDB persistence and uniqueness are real.
        voyage = SimpleNamespace(embed=AsyncMock(return_value=[[0.1] * 1024 for _ in range(12)]))
        monkeypatch.setattr("chainlex.db.corpus_seeding.VoyageEmbeddings", lambda *args: voyage)
        configured = Settings(_env_file=None, database=name, voyage_api_key="test-only-key")
        embedded = await seed_latest(db, configured)
        assert embedded["regulations"]["inserted"] == 12
        assert await db.regulations.count_documents({"embedding": {"$size": 1024}}) == 12
        rule = await db.regulations.find_one({"tenant_id": "bank_a"})
        await db.regulations.update_one(
            {"_id": rule["_id"]}, {"$set": {"review_status": "VERIFIED", "is_active": False}}
        )
        repeated = await seed_latest(db, configured)
        assert repeated["regulations"]["inserted"] == 0
        assert repeated["regulations"]["existing_preserved"] == 12
        assert voyage.embed.await_count == 1
        assert (await db.regulations.find_one({"_id": rule["_id"]}))["review_status"] == "VERIFIED"

        other = Settings(_env_file=None, database=name, demo_tenant_id="bank_b", voyage_api_key="")
        await seed_latest(db, other)
        assert await db.policies.count_documents({"tenant_id": "bank_b"}) == 15
        assert await db.policies.count_documents({"tenant_id": "bank_a"}) == 15
    finally:
        await client.drop_database(name)
        await client.close()
