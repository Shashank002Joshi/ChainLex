"""Idle FSM scaffold worker; durable leg handlers are not implemented yet."""

import argparse
import asyncio
import logging
import signal

from pymongo.errors import PyMongoError

from chainlex.config import Settings
from chainlex.db.connection import create_client

logger = logging.getLogger("chainlex.worker")


async def run(settings: Settings, *, once: bool = False) -> None:
    client = create_client(settings)
    try:
        await client[settings.database].command("ping")
        topology = await client.admin.command("hello")
        if not (topology.get("setName") or topology.get("msg") == "isdbgrid"):
            raise ValueError("Worker requires a replica set or sharded cluster")
        logger.info("worker=fsm_scaffold_idle database=ready fsm_processing=not_implemented")
        if once:
            return
        stopped = asyncio.Event()
        loop = asyncio.get_running_loop()
        signals = (signal.SIGINT, signal.SIGTERM)
        for sig in signals:
            loop.add_signal_handler(sig, stopped.set)
        try:
            await stopped.wait()
        finally:
            for sig in signals:
                loop.remove_signal_handler(sig)
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once", action="store_true", help="Check startup and exit without processing"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        asyncio.run(run(Settings(), once=args.once))
    except (ValueError, PyMongoError):
        parser.exit(
            1, "Worker startup failed; check MongoDB settings and replica-set connectivity.\n"
        )
