"""Persist identity and fictional hold effect atomically in one MongoDB document."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from chainlex.connectors.simulator import prepare_action
from chainlex.domain.models import DispatchReference, PreparedAction, ProbeOutcome, ProbeResult


class OperationConflict(ValueError):
    """An idempotency key was reused with a different payload."""


class InvalidPreparedAction(ValueError):
    """Prepared identity or payload digest does not match its contents."""


class MongoOperationStore:
    def __init__(
        self,
        collection,
        confirmation_seconds: float = 2,
        now: Callable[[], datetime] | None = None,
    ):
        self.collection = collection
        self.confirmation_seconds = confirmation_seconds
        self.now = now if now is not None else lambda: datetime.now(UTC)

    async def dispatch(self, prepared: PreparedAction) -> DispatchReference:
        expected = prepare_action(prepared.action, prepared.idempotency_key)
        if expected != prepared:
            raise InvalidPreparedAction("Prepared identity or digest does not match its payload")
        now = self.now()
        document = {
            "_id": prepared.operation_id,
            "tenant_id": prepared.action.tenant_id,
            "schema_version": 1,
            "idempotency_key": prepared.idempotency_key,
            "payload_digest": prepared.payload_digest,
            "action": prepared.action.model_dump(),
            "effect": {"settlement_id": prepared.action.settlement_id, "status": "HELD"},
            "created_at": now,
            "confirmed_at": now + timedelta(seconds=self.confirmation_seconds),
            "is_simulated": True,
        }
        try:
            saved = await self.collection.find_one_and_update(
                {"_id": prepared.operation_id},
                {"$setOnInsert": document},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            saved = await self.collection.find_one({"_id": prepared.operation_id})
        if saved is None:
            raise RuntimeError("Simulator operation could not be read after insertion")
        if saved["payload_digest"] != prepared.payload_digest:
            raise OperationConflict("Idempotency key already belongs to a different payload")
        return DispatchReference(operation_id=prepared.operation_id)

    async def probe(self, operation_id: str, tenant_id: str) -> ProbeResult:
        saved = await self.collection.find_one({"_id": operation_id, "tenant_id": tenant_id})
        if saved is None:
            return ProbeResult(operation_id=operation_id, outcome=ProbeOutcome.NOT_FOUND)
        outcome = (
            ProbeOutcome.CONFIRMED if self.now() >= saved["confirmed_at"] else ProbeOutcome.PENDING
        )
        return ProbeResult(
            operation_id=operation_id,
            outcome=outcome,
            settlement_id=saved["effect"]["settlement_id"],
            effect=saved["effect"]["status"],
        )
