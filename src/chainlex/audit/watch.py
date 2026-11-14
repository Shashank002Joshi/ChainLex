"""Resumable governance notifications; correctness always uses authoritative reads."""

import asyncio
import logging

from pymongo.errors import PyMongoError

from chainlex.audit.models import utcnow

logger = logging.getLogger(__name__)


async def watch_governance(database, worker_id, wakeup, stopped):
    cursor_id = f"audit-controls:{worker_id}"
    while not stopped.is_set():
        saved = await database.worker_cursors.find_one({"worker_id": cursor_id})
        options = {"max_await_time_ms": 1000, "full_document": "updateLookup"}
        if saved and saved.get("resume_token"):
            options["resume_after"] = saved["resume_token"]
        try:
            async with await database.tenant_controls.watch(**options) as stream:
                while not stopped.is_set():
                    change = await stream.try_next()
                    if change:
                        wakeup.set()
                    if stream.resume_token:
                        await database.worker_cursors.update_one(
                            {"worker_id": cursor_id},
                            {
                                "$set": {
                                    "tenant_id": "__system__",
                                    "schema_version": 1,
                                    "worker_id": cursor_id,
                                    "resume_token": stream.resume_token,
                                    "updated_at": utcnow(),
                                }
                            },
                            upsert=True,
                        )
        except PyMongoError as exc:
            logger.warning(
                "governance_watch_unavailable error=%s polling=active", type(exc).__name__
            )
            if getattr(exc, "code", None) in {136, 260, 286}:
                # Lost history: poll authoritative state, then start a fresh stream.
                await database.worker_cursors.delete_one({"worker_id": cursor_id})
                wakeup.set()
            try:
                await asyncio.wait_for(stopped.wait(), timeout=5)
            except TimeoutError:
                pass
