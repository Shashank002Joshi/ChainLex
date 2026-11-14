"""Explicit database setup commands; never provision automatically on import."""

import argparse
import asyncio
import json
from uuid import uuid4

from pymongo.errors import PyMongoError

from chainlex.config import Settings
from chainlex.db.connection import create_client
from chainlex.db.indexes import bootstrap


async def preflight(client, database) -> dict:
    await database.command("ping")
    topology = await client.admin.command("hello")
    if not (topology.get("setName") or topology.get("msg") == "isdbgrid"):
        raise ValueError("MongoDB must be a replica set or sharded cluster")
    collection = database["_preflight"]
    marker = str(uuid4())
    # Materialize the collection before opening the transaction.
    await collection.insert_one({"_id": marker, "phase": "before"})
    try:
        async with client.start_session() as session:
            async with await session.start_transaction():
                await collection.update_one(
                    {"_id": marker}, {"$set": {"phase": "committed"}}, session=session
                )
        document = await collection.find_one({"_id": marker})
        if document is None or document["phase"] != "committed":
            raise ValueError("Transaction commit was not visible")
    finally:
        await collection.delete_one({"_id": marker})
    return {"database": "reachable", "topology": "transaction_capable", "transaction": "committed"}


async def seed_demo(database) -> dict:
    for index in range(6):
        tenant = "bank_a" if index < 3 else "bank_b"
        document = {
            "_id": f"demo-entity-{index + 1}",
            "tenant_id": tenant,
            "schema_version": 1,
            "network": "simulation",
            "address": f"0x{index + 1:040x}",
            "label": f"Fictional Demo Counterparty {index + 1}",
            "jurisdiction": "USA" if index % 2 == 0 else "SGP",
            "is_demo_fixture": True,
            "review_status": "UNVERIFIED",
        }
        await database.entities.update_one(
            {"_id": document["_id"]}, {"$setOnInsert": document}, upsert=True
        )
    for index in range(4):
        document = {
            "_id": f"demo-case-{index + 1}",
            "tenant_id": "bank_a" if index < 2 else "bank_b",
            "schema_version": 1,
            "is_demo_fixture": True,
            "review_status": "UNVERIFIED",
            "is_active": False,
            "narrative": "Fictional precedent fixture; no legal finding or regulatory filing.",
        }
        await database.compliance_cases.update_one(
            {"_id": document["_id"]}, {"$setOnInsert": document}, upsert=True
        )
    return {"entities": 6, "cases": 4, "review_status": "UNVERIFIED"}


async def run(command: str) -> dict:
    settings = Settings()
    client = create_client(settings)
    try:
        database = client[settings.database]
        if command == "preflight":
            return await preflight(client, database)
        if command == "bootstrap":
            await bootstrap(database)
            return {"bootstrap": "complete"}
        return await seed_demo(database)
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("bootstrap", "preflight", "seed-demo"))
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args.command))
    except (ValueError, PyMongoError):
        parser.exit(1, "Database command failed; check settings, connectivity, and permissions.\n")
    print(json.dumps(result))
