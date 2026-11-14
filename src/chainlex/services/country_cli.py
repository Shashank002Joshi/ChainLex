"""Validate country corpus offline or explicitly ingest into MongoDB with Voyage."""

import argparse
import asyncio
import json
from pathlib import Path

import httpx

from chainlex.config import Settings
from chainlex.db.connection import create_client
from chainlex.services.country_rules import Regulation, ReviewPolicy, VoyageEmbeddings, ingest_rules


def load_corpus(directory: Path, *, regulations_only: bool = False):
    rules = [
        Regulation.model_validate(r)
        for r in json.loads((directory / "regulations.json").read_text())
    ]
    policies = (
        []
        if regulations_only
        else [
            ReviewPolicy.model_validate(p)
            for p in json.loads((directory / "policies.json").read_text())
        ]
    )
    ids = {r.rule_id for r in rules}
    if len(ids) != len(rules) or len({p.policy_id for p in policies}) != len(policies):
        raise ValueError("Duplicate rule or policy ID")
    for policy in policies:
        if not policy.source_rule_ids or not set(policy.source_rule_ids) <= ids:
            raise ValueError("Policy references missing source rules")
        if any(
            r.jurisdiction != policy.jurisdiction
            for r in rules
            if r.rule_id in policy.source_rule_ids
        ):
            raise ValueError("Policy/source jurisdiction mismatch")
    return rules, policies


async def ingest(directory: Path, endpoint: str, *, regulations_only: bool = False):
    rules, policies = load_corpus(directory, regulations_only=regulations_only)
    settings = Settings()
    client = create_client(settings)
    try:
        db = client[settings.database]
        async with httpx.AsyncClient(timeout=30) as http:
            voyage = VoyageEmbeddings(http, settings.voyage_api_key.get_secret_value(), endpoint)
            await ingest_rules(db, voyage, rules, settings.demo_tenant_id)
        for policy in policies:
            document = policy.model_dump(mode="json")
            document.update(
                {
                    "_id": f"{settings.demo_tenant_id}:{policy.policy_id}:v{policy.version}",
                    "tenant_id": settings.demo_tenant_id,
                    "schema_version": 1,
                    "is_active": False,
                    "review_status": "UNVERIFIED",
                }
            )
            await db.policies.update_one(
                {"_id": document["_id"]}, {"$setOnInsert": document}, upsert=True
            )
    finally:
        await client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "ingest"])
    parser.add_argument("--directory", type=Path, default=Path("data/country_rules"))
    parser.add_argument("--endpoint", default="https://ai.mongodb.com/v1/embeddings")
    parser.add_argument("--regulations-only", action="store_true")
    args = parser.parse_args()
    rules, policies = load_corpus(args.directory, regulations_only=args.regulations_only)
    if args.command == "ingest":
        asyncio.run(ingest(args.directory, args.endpoint, regulations_only=args.regulations_only))
    print(json.dumps({"rules": len(rules), "policies": len(policies), "command": args.command}))


if __name__ == "__main__":
    main()
