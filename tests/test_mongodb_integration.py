import asyncio
import os
from uuid import uuid4

import pytest
from pymongo import AsyncMongoClient
from pymongo.errors import DuplicateKeyError

from chainlex.connectors.simulator import prepare_action
from chainlex.db.cli import preflight, seed_demo
from chainlex.db.indexes import LegacySchemaError, bootstrap
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
        await database.job_executions.insert_one({"_id": "legacy-preserved"})
        await bootstrap(database)
        await bootstrap(database)
        assert await database.job_executions.find_one({"_id": "legacy-preserved"}) is not None
        assert "compliance_fsms" in await database.list_collection_names()
        assert "tenant_controls" in await database.list_collection_names()
        await seed_demo(database)
        await seed_demo(database)
        assert await database.entities.count_documents({}) == 6
        assert await database.compliance_cases.count_documents({}) == 4
        assert await database.compliance_cases.count_documents({"is_active": True}) == 0

        audit = {
            "tenant_id": "bank_a",
            "schema_version": 1,
            "fsm_id": "fsm-1",
            "sequence": 1,
            "event_id": "event-1",
        }
        await database.audit_ledger.insert_one(dict(audit))
        with pytest.raises(DuplicateKeyError):
            await database.audit_ledger.insert_one(audit | {"sequence": 2})
        await database.audit_ledger.insert_one(audit | {"fsm_id": "fsm-2"})

        fsm = {
            "tenant_id": "bank_a",
            "schema_version": 1,
            "fsm_id": "fsm-1",
            "idempotency_key": "request-1",
        }
        await database.compliance_fsms.insert_one(dict(fsm))
        with pytest.raises(DuplicateKeyError):
            await database.compliance_fsms.insert_one(fsm | {"fsm_id": "fsm-2"})
        await database.compliance_fsms.insert_one(fsm | {"tenant_id": "bank_b"})

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

        await database.agent_action_proposals.create_index(
            [("tenant_id", 1), ("job_id", 1), ("version", 1)],
            unique=True,
            name="legacy_job_version",
        )
        legacy_proposal = {
            "tenant_id": "bank_a",
            "schema_version": 1,
            "job_id": "legacy-1",
            "version": 1,
        }
        await database.agent_action_proposals.insert_one(legacy_proposal)
        with pytest.raises(LegacySchemaError):
            await bootstrap(database)
        assert await database.agent_action_proposals.count_documents({"job_id": "legacy-1"}) == 1
        assert "legacy_job_version" in await database.agent_action_proposals.index_information()
    finally:
        await client.drop_database(name)
        await client.close()
