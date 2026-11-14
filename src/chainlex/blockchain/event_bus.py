"""Reactive Web3 Event Bus powered by MongoDB Atlas Change Streams."""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class Web3EventBus:
    """
    Subscribes to contract_events in MongoDB Atlas via Change Streams
    to push on-chain events to agent workflows with zero polling.
    """

    def __init__(
        self,
        db: Any,
        on_settlement_initiated: Callable[[dict[str, Any]], Any] | None = None,
        tenant_id: str = "bank_a",
    ):
        self.db = db
        self.on_settlement_initiated = on_settlement_initiated
        self.tenant_id = tenant_id
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Starts the change stream listener background coroutine."""
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._listen_loop())

    async def stop(self) -> None:
        """Stops the change stream listener cleanly."""
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _handle_event(self, doc: dict[str, Any]) -> None:
        event_name = doc.get("event_name")
        params = doc.get("decoded_params", {})
        if event_name == "SettlementInitiated" and self.on_settlement_initiated:
            logger.info(
                "EventBus: Pushing SettlementInitiated to workflow: %s", params.get("settlement_id")
            )
            if asyncio.iscoroutinefunction(self.on_settlement_initiated):
                await self.on_settlement_initiated(params)
            else:
                self.on_settlement_initiated(params)

    async def _listen_loop(self) -> None:
        pipeline = [
            {
                "$match": {
                    "operationType": "insert",
                    "fullDocument.tenant_id": self.tenant_id,
                    "fullDocument.event_name": "SettlementInitiated",
                    "fullDocument.is_orphaned": False,
                }
            }
        ]

        try:
            # In async PyMongo, watch() is a coroutine returning an AsyncChangeStream
            stream = await self.db.contract_events.watch(pipeline)
            async with stream:
                while not self._stop_event.is_set():
                    try:
                        change = await asyncio.wait_for(stream.next(), timeout=1.0)
                        doc = change.get("fullDocument")
                        if doc:
                            await self._handle_event(doc)
                    except TimeoutError:
                        continue
        except Exception as e:
            logger.warning("Change stream stopped: %s", e)
            await self._stop_event.wait()
