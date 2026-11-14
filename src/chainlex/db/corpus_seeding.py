"""Seed policies independently; regulations require actual valid Voyage embeddings."""

from pathlib import Path

import httpx

from chainlex.config import Settings
from chainlex.db.seeding import seed_demo
from chainlex.services.country_corpus import load_bank_corpus, load_corpus
from chainlex.services.country_rules import ingest_policies, ingest_rules
from chainlex.services.embeddings import VoyageEmbeddings


async def seed_latest(database, settings: Settings, directory: Path | None = None) -> dict:
    # Validate all source files before any fixture or policy write.
    rules, policies = load_corpus(directory)
    bank_policies = load_bank_corpus(directory)
    keys = [(policy.policy_id, policy.version) for policy in [*policies, *bank_policies]]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate policy ID/version in the target tenant")

    result = await seed_demo(database)
    result["database"] = settings.database
    result["tenant_id"] = settings.demo_tenant_id
    result["policies"] = await ingest_policies(
        database, [*policies, *bank_policies], settings.demo_tenant_id
    )
    key = settings.voyage_api_key.get_secret_value()
    if not key:
        result["regulations"] = {
            "status": "skipped",
            "available": len(rules),
            "inserted": 0,
            "reason": "CHAINLEX_VOYAGE_API_KEY_NOT_CONFIGURED",
        }
        return result

    async with httpx.AsyncClient(timeout=30) as http:
        voyage = VoyageEmbeddings(http, key, settings.embedding_endpoint)
        counts = await ingest_rules(database, voyage, rules, settings.demo_tenant_id)
    result["regulations"] = {"status": "complete", **counts}
    return result
