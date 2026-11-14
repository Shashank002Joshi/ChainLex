import asyncio
import json
import os
import sys
from uuid import uuid4

import pytest
from pymongo import AsyncMongoClient

from chainlex.db import seed_reset
from chainlex.db.indexes import bootstrap
from chainlex.db.seed_reset import RUNTIME_COLLECTIONS, SeedResetError, reset_seed_demo
from chainlex.db.seeding import seed_demo

pytestmark = pytest.mark.integration


async def _cli(uri, name, *options):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "from chainlex.db.cli import main; main()",
        "seed-demo",
        "--reset",
        "--database",
        name,
        *options,
        env=dict(os.environ, CHAINLEX_MONGODB_URI=uri),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, stderr.decode()
    return json.loads(stdout)


async def test_preview_atomic_reset_and_preservation(monkeypatch):
    uri = os.environ.get("CHAINLEX_TEST_MONGODB_URI")
    if not uri:
        pytest.skip("Set CHAINLEX_TEST_MONGODB_URI for a disposable MongoDB replica set")
    client = AsyncMongoClient(uri, serverSelectionTimeoutMS=5000, tz_aware=True)
    name = "chainlex_manual_verify_" + uuid4().hex
    database = client[name]
    try:
        await bootstrap(database)
        await seed_demo(database)
        for collection in RUNTIME_COLLECTIONS:
            await database[collection].insert_one(
                {
                    "_id": "runtime-1",
                    "tenant_id": "bank_a",
                    "schema_version": 1,
                    "fsm_id": "fsm-1",
                    "idempotency_key": "request-1",
                    "sequence": 1,
                    "event_id": "event-1",
                    "version": 1,
                }
            )
        await database.entities.update_one(
            {"_id": "demo-entity-1"}, {"$set": {"label": "Edited fixture", "extra": True}}
        )
        await database.compliance_cases.update_one(
            {"_id": "demo-case-1"}, {"$set": {"is_active": True, "review_status": "APPROVED"}}
        )
        for collection in (
            "entities",
            "compliance_cases",
            "policies",
            "regulations",
            "tenant_controls",
        ):
            await database[collection].insert_one(
                {
                    "_id": "unrelated-1",
                    "tenant_id": "custom_tenant",
                    "schema_version": 1,
                    "network": "simulation",
                    "address": "custom-address",
                    "keep": True,
                }
            )
        await database.unknown_collection.insert_one({"_id": "untouched"})
        indexes = {
            name: await database[name].index_information()
            for name in await database.list_collection_names()
        }
        validator = (await database.command("listCollections", filter={"name": "entities"}))[
            "cursor"
        ]["firstBatch"][0]["options"]

        # Ordinary seeding preserves edits and existing simulator/FSM run records.
        await seed_demo(database)
        assert (await database.entities.find_one({"_id": "demo-entity-1"}))[
            "label"
        ] == "Edited fixture"
        preview = await _cli(uri, name)
        assert preview["mode"] == "preview"
        assert preview["would_delete_runtime"] == dict.fromkeys(RUNTIME_COLLECTIONS, 1)
        for collection in RUNTIME_COLLECTIONS:
            assert await database[collection].count_documents({}) == 1

        # A seed failure after deletion must roll the entire transaction back.
        async def failed_restore(*args, **kwargs):
            raise RuntimeError("Injected fixture restoration failure")

        with monkeypatch.context() as patch:
            patch.setattr(seed_reset, "seed_demo", failed_restore)
            with pytest.raises(RuntimeError, match="Injected"):
                await reset_seed_demo(database, execute=True, confirmation=name)
        for collection in RUNTIME_COLLECTIONS:
            assert await database[collection].count_documents({}) == 1

        # IDs alone do not authorize overwriting records that are no longer demo fixtures.
        await database.entities.update_one(
            {"_id": "demo-entity-1"}, {"$set": {"is_demo_fixture": False}}
        )
        with pytest.raises(SeedResetError, match="non-demo"):
            await reset_seed_demo(database, execute=True, confirmation=name)
        assert await database.simulator_operations.count_documents({}) == 1
        await database.entities.update_one(
            {"_id": "demo-entity-1"}, {"$set": {"is_demo_fixture": True}}
        )

        result = await _cli(uri, name, "--execute", "--confirm-db", name)
        assert result["mode"] == "reset"
        assert result["deleted_runtime"] == dict.fromkeys(RUNTIME_COLLECTIONS, 1)
        for collection in RUNTIME_COLLECTIONS:
            assert await database[collection].count_documents({}) == 0
        restored = await database.entities.find_one({"_id": "demo-entity-1"})
        assert restored["label"] == "Fictional Demo Counterparty 1"
        assert "extra" not in restored
        assert await database.entities.count_documents({"is_demo_fixture": True}) == 6
        assert (
            await database.compliance_cases.count_documents(
                {
                    "is_demo_fixture": True,
                    "review_status": "UNVERIFIED",
                    "is_active": False,
                }
            )
            == 4
        )
        for collection in (
            "entities",
            "compliance_cases",
            "policies",
            "regulations",
            "tenant_controls",
        ):
            assert (await database[collection].find_one({"_id": "unrelated-1"}))["keep"] is True
        assert await database.unknown_collection.find_one({"_id": "untouched"}) is not None
        for collection, expected in indexes.items():
            assert await database[collection].index_information() == expected
        options = (await database.command("listCollections", filter={"name": "entities"}))[
            "cursor"
        ]["firstBatch"][0]["options"]
        assert options == validator
    finally:
        await client.drop_database(name)
        await client.close()
