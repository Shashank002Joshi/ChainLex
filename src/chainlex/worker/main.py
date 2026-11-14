"""Durable audit worker; settlement dispatch remains a separate scaffold."""

import argparse
import asyncio
import logging
import signal
from uuid import uuid4

import httpx
from pymongo.errors import PyMongoError

from chainlex.audit.engine import DurableCompletionAgent
from chainlex.audit.reports import ReportStore
from chainlex.audit.repository import AuditRepository
from chainlex.audit.watch import watch_governance
from chainlex.config import Settings
from chainlex.db.connection import create_client
from chainlex.services.embeddings import VoyageEmbeddings

logger = logging.getLogger("chainlex.worker")


async def run(settings: Settings, *, once: bool = False, drain: bool = False) -> None:
    client = create_client(settings)
    try:
        await client[settings.database].command("ping")
        topology = await client.admin.command("hello")
        if not (topology.get("setName") or topology.get("msg") == "isdbgrid"):
            raise ValueError("Worker requires a replica set or sharded cluster")
        logger.info(
            "worker=audit_agents database=ready "
            "reasoning=scripted_demo settlement_dispatch=disabled"
        )
        if once:
            return
        stopped = asyncio.Event()
        wakeup = asyncio.Event()
        database = client[settings.database]
        worker_id = settings.audit_worker_id + ":" + uuid4().hex
        loop = asyncio.get_running_loop()
        signals = (signal.SIGINT, signal.SIGTERM)
        for sig in signals:
            loop.add_signal_handler(sig, stopped.set)
        watcher = (
            asyncio.create_task(
                watch_governance(database, settings.audit_worker_id, wakeup, stopped)
            )
            if not drain
            else None
        )
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                voyage = VoyageEmbeddings(
                    http, settings.voyage_api_key.get_secret_value(), settings.embedding_endpoint
                )
                agent = DurableCompletionAgent(
                    AuditRepository(database, settings.lease_seconds),
                    voyage,
                    ReportStore(database),
                    settings,
                )
                while not stopped.is_set():
                    wakeup.clear()
                    if await agent.run_once(worker_id):
                        continue
                    if drain:
                        break
                    try:
                        await asyncio.wait_for(wakeup.wait(), timeout=settings.poll_seconds)
                    except TimeoutError:
                        pass
        finally:
            if watcher:
                watcher.cancel()
                import contextlib

                with contextlib.suppress(asyncio.CancelledError):
                    await watcher
            for sig in signals:
                loop.remove_signal_handler(sig)
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once", action="store_true", help="Check startup and exit without processing"
    )
    parser.add_argument(
        "--drain",
        action="store_true",
        help="Process ready audit steps, then exit at idle/human waits",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        asyncio.run(run(Settings(), once=args.once, drain=args.drain))
    except (ValueError, PyMongoError):
        parser.exit(
            1, "Worker startup failed; check MongoDB settings and replica-set connectivity.\n"
        )
