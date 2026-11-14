from copy import deepcopy
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from chainlex.connectors.simulator import SimulatorConnector, prepare_action
from chainlex.domain.models import HoldAction, ProbeOutcome
from chainlex.simulator.app import create_app
from chainlex.simulator.store import InvalidPreparedAction, MongoOperationStore, OperationConflict


class FakeCollection:
    """Test double for operation contract checks; not a MongoDB durability test."""

    def __init__(self):
        self.documents = {}

    async def find_one_and_update(self, query, update, **kwargs):
        self.documents.setdefault(query["_id"], deepcopy(update["$setOnInsert"]))
        return deepcopy(self.documents[query["_id"]])

    async def find_one(self, query):
        document = self.documents.get(query["_id"])
        if document is None or any(document[key] != value for key, value in query.items()):
            return None
        return deepcopy(document)


@pytest.fixture
def prepared():
    action = HoldAction(tenant_id="bank_a", settlement_id="settlement-1", amount_minor=10_000_000)
    return prepare_action(action, "action-1")


async def test_retries_have_one_effect_and_survive_store_recreation(prepared):
    collection = FakeCollection()
    first = MongoOperationStore(collection, confirmation_seconds=0)
    reference = await first.dispatch(prepared)
    restarted = MongoOperationStore(collection, confirmation_seconds=0)
    assert await restarted.dispatch(prepared) == reference
    assert len(collection.documents) == 1
    result = await restarted.probe(prepared.operation_id, "bank_a")
    assert result.outcome == ProbeOutcome.CONFIRMED
    assert result.settlement_id == "settlement-1"
    assert result.effect == "HELD"


async def test_conflicting_payload_cannot_replace_original_effect(prepared):
    collection = FakeCollection()
    store = MongoOperationStore(collection)
    await store.dispatch(prepared)
    changed = prepare_action(
        prepared.action.model_copy(update={"settlement_id": "different-target"}), "action-1"
    )
    with pytest.raises(OperationConflict):
        await store.dispatch(changed)
    assert collection.documents[prepared.operation_id]["effect"]["settlement_id"] == "settlement-1"


async def test_confirmation_waits_and_other_tenant_cannot_probe(prepared):
    clock = [datetime(2026, 11, 14, tzinfo=UTC)]
    store = MongoOperationStore(FakeCollection(), now=lambda: clock[0])
    await store.dispatch(prepared)
    assert (await store.probe(prepared.operation_id, "bank_a")).outcome == ProbeOutcome.PENDING
    assert (await store.probe(prepared.operation_id, "bank_b")).outcome == ProbeOutcome.NOT_FOUND
    clock[0] += timedelta(seconds=3)
    assert (await store.probe(prepared.operation_id, "bank_a")).outcome == ProbeOutcome.CONFIRMED


async def test_tampered_prepared_action_has_no_effect(prepared):
    collection = FakeCollection()
    store = MongoOperationStore(collection)
    altered = prepared.model_copy(update={"payload_digest": "0" * 64})
    with pytest.raises(InvalidPreparedAction):
        await store.dispatch(altered)
    assert not collection.documents


def test_simulator_requires_separate_token(settings, prepared):
    store = MongoOperationStore(FakeCollection())
    with TestClient(create_app(settings, store=store)) as client:
        assert client.get("/health/live").status_code == 200
        assert client.post("/operations", json=prepared.model_dump()).status_code == 401
        response = client.post(
            "/operations",
            json=prepared.model_dump(),
            headers={"Authorization": "Bearer analyst-test-token"},
        )
        assert response.status_code == 401
        assert not store.collection.documents


async def test_http_connector_round_trip(settings, prepared):
    store = MongoOperationStore(FakeCollection(), confirmation_seconds=0)
    transport = httpx.ASGITransport(app=create_app(settings, store=store))
    async with httpx.AsyncClient(transport=transport, base_url="http://simulator") as client:
        connector = SimulatorConnector(client, "simulator-test-token")
        saved = await connector.prepare(prepared.action, prepared.idempotency_key)
        assert saved == prepared
        reference = await connector.dispatch(saved)
        result = await connector.probe(saved)
        assert result.operation_id == reference.operation_id
        assert result.outcome == ProbeOutcome.CONFIRMED


async def test_http_connector_propagates_errors(settings, prepared):
    store = MongoOperationStore(FakeCollection())
    transport = httpx.ASGITransport(app=create_app(settings, store=store))
    async with httpx.AsyncClient(transport=transport, base_url="http://simulator") as client:
        connector = SimulatorConnector(client, "wrong-token")
        with pytest.raises(httpx.HTTPStatusError):
            await connector.dispatch(prepared)


def test_simulator_has_no_in_memory_fallback(settings, prepared):
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/operations",
            json=prepared.model_dump(),
            headers={"Authorization": "Bearer simulator-test-token"},
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "DATABASE_NOT_CONFIGURED"
