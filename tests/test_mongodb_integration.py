import asyncio
import os
from uuid import uuid4

import pytest
from pymongo import AsyncMongoClient

from chainlex.connectors.simulator import prepare_action
from chainlex.db.cli import preflight, seed_demo
from chainlex.db.indexes import bootstrap
from chainlex.domain.models import HoldAction, ProbeOutcome
from chainlex.simulator.store import MongoOperationStore, OperationConflict

pytestmark = pytest.mark.integration


async def test_real_database_bootstrap_and_simulator_persistence():
    uri = os.environ.get("CHAINLEX_TEST_MONGODB_URI")
    if not uri:
        pytest.skip("Set CHAINLEX_TEST_MONGODB_URI for a disposable MongoDB replica set")
    client = AsyncMongoClient(uri, serverSelectionTimeoutMS=3000, tz_aware=True)
    name = f"chainlex_test_{uuid4().hex}"
    database = client[name]
    try:
        assert (await preflight(client, database))["transaction"] == "committed"
        await bootstrap(database)
        await bootstrap(database)
        await seed_demo(database)
        await seed_demo(database)
        assert await database.entities.count_documents({}) == 6
        assert await database.compliance_cases.count_documents({}) == 4
        assert await database.compliance_cases.count_documents({"is_active": True}) == 0

        action = HoldAction(tenant_id="bank_a", settlement_id="s-1", amount_minor=10_000_000)
        prepared = prepare_action(action, "integration-1")
        store = MongoOperationStore(database.simulator_operations, confirmation_seconds=0)
        references = await asyncio.gather(*(store.dispatch(prepared) for _ in range(8)))
        assert len({reference.operation_id for reference in references}) == 1
        assert await database.simulator_operations.count_documents({}) == 1
        restarted = MongoOperationStore(database.simulator_operations, confirmation_seconds=0)
        assert (
            await restarted.probe(prepared.operation_id, "bank_a")
        ).outcome == ProbeOutcome.CONFIRMED
        changed = prepare_action(
            action.model_copy(update={"settlement_id": "s-2"}), "integration-1"
        )
        with pytest.raises(OperationConflict):
            await restarted.dispatch(changed)
    finally:
        await client.drop_database(name)
        await client.close()
