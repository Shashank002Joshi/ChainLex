"""Validate country corpus offline or explicitly ingest into MongoDB with Voyage."""

import argparse
import asyncio
import json
from pathlib import Path

import httpx

from chainlex.config import Settings
from chainlex.db.connection import create_client
from chainlex.services.country_corpus import load_bank_corpus, load_corpus
from chainlex.services.country_rules import ingest_policies, ingest_rules
from chainlex.services.embeddings import VoyageEmbeddings


async def ingest(directory: Path | None, endpoint: str | None, *, regulations_only: bool = False):
    rules, policies = load_corpus(directory, regulations_only=regulations_only)
    bank_policies = [] if regulations_only else load_bank_corpus(directory)
    settings = Settings()
    client = create_client(settings)
    try:
        db = client[settings.database]
        async with httpx.AsyncClient(timeout=30) as http:
            voyage = VoyageEmbeddings(
                http,
                settings.voyage_api_key.get_secret_value(),
                endpoint if endpoint is not None else settings.embedding_endpoint,
            )
            await ingest_rules(db, voyage, rules, settings.demo_tenant_id)
        await ingest_policies(db, [*policies, *bank_policies], settings.demo_tenant_id)
    finally:
        await client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "ingest"])
    parser.add_argument("--directory", type=Path, default=None)
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--regulations-only", action="store_true")
    args = parser.parse_args()
    rules, policies = load_corpus(args.directory, regulations_only=args.regulations_only)
    bank_policies = [] if args.regulations_only else load_bank_corpus(args.directory)
    if args.command == "ingest":
        asyncio.run(ingest(args.directory, args.endpoint, regulations_only=args.regulations_only))
    print(
        json.dumps(
            {
                "rules": len(rules),
                "policies": len(policies),
                "bank_policies": len(bank_policies),
                "command": args.command,
            }
        )
    )


if __name__ == "__main__":
    main()
