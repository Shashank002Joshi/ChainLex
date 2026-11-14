"""Explicit database setup commands; never provision automatically on import."""

import argparse
import asyncio
import json
from uuid import uuid4

import httpx
from pymongo.errors import PyMongoError

from chainlex.config import Settings
from chainlex.db.connection import create_client
from chainlex.db.corpus_seeding import seed_latest
from chainlex.db.indexes import LegacySchemaError, bootstrap
from chainlex.db.seed_reset import SeedResetError, reset_seed_demo, validate_reset_target


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


async def run(
    command: str,
    *,
    database_name: str | None = None,
    reset: bool = False,
    execute: bool = False,
    confirmation: str | None = None,
) -> dict:
    validate_reset_options(command, database_name, reset, execute, confirmation)
    settings = Settings(database=database_name) if database_name is not None else Settings()
    client = create_client(settings)
    try:
        database = client[settings.database]
        if command == "preflight":
            return await preflight(client, database)
        if command == "bootstrap":
            await bootstrap(database)
            return {"bootstrap": "complete"}
        if reset:
            return await reset_seed_demo(database, execute=execute, confirmation=confirmation)
        return await seed_latest(database, settings)
    finally:
        await client.close()


def validate_reset_options(command, database_name, reset, execute, confirmation) -> None:
    if (execute or confirmation is not None) and not reset:
        raise SeedResetError("--execute and --confirm-db require seed-demo --reset")
    if reset:
        if command != "seed-demo":
            raise SeedResetError("--reset is supported only by seed-demo")
        if database_name is None:
            raise SeedResetError("--reset requires an explicit --database chainlex_manual_NAME")
        validate_reset_target(database_name, execute=execute, confirmation=confirmation)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("bootstrap", "preflight", "seed-demo"))
    parser.add_argument("--database", help="Explicit database namespace override")
    parser.add_argument(
        "--reset", action="store_true", help="Preview resetting manual runs and demo fixtures"
    )
    parser.add_argument("--execute", action="store_true", help="Execute the previewed reset")
    parser.add_argument("--confirm-db", help="Exact manual database name required with --execute")
    args = parser.parse_args()
    try:
        result = asyncio.run(
            run(
                args.command,
                database_name=args.database,
                reset=args.reset,
                execute=args.execute,
                confirmation=args.confirm_db,
            )
        )
    except (LegacySchemaError, SeedResetError) as exc:
        parser.exit(1, f"{exc}\n")
    except httpx.HTTPError:
        parser.exit(
            1,
            "Policies were seeded independently, but Voyage embedding failed. "
            "Check the API key and provider availability, then rerun seed-demo.\n",
        )
    except (ValueError, PyMongoError):
        parser.exit(1, "Database command failed; check settings, connectivity, and permissions.\n")
    print(json.dumps(result))
