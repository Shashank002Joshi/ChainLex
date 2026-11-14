"""Opt-in proof that real Voyage + Atlas memory changes the next audit's behavior."""

import asyncio
import os
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from pymongo import AsyncMongoClient

from chainlex.audit.agents import AuditableActionAgent
from chainlex.audit.memory import GovernedMemoryAgent
from chainlex.audit.models import AuditConflict, MemoryCreate, MemoryInvalidation, utcnow
from chainlex.audit.repository import AuditRepository
from chainlex.audit.scenarios import adapt_context, scenario_input
from chainlex.audit.search import provision_audit_indexes
from chainlex.db.indexes import bootstrap
from chainlex.services.embeddings import VoyageEmbeddings

pytestmark = pytest.mark.integration


async def test_real_voyage_vector_search_isolation_influence_and_invalidation():
    uri, key = (
        os.environ.get("CHAINLEX_TEST_MONGODB_URI"),
        os.environ.get("CHAINLEX_TEST_VOYAGE_API_KEY"),
    )
    if not uri or not key:
        pytest.skip(
            "Set CHAINLEX_TEST_MONGODB_URI and CHAINLEX_TEST_VOYAGE_API_KEY for live search"
        )
    mongo = AsyncMongoClient(uri, serverSelectionTimeoutMS=5000, tz_aware=True)
    name = "chainlex_test_live_audit_" + uuid4().hex
    db = mongo[name]
    try:
        await bootstrap(db)
        print("live audit: provisioning two disposable Vector Search indexes", flush=True)
        await provision_audit_indexes(db)
        repo = AuditRepository(db)
        async with httpx.AsyncClient(timeout=30) as http:
            voyage = VoyageEmbeddings(
                http,
                key,
                os.environ.get(
                    "CHAINLEX_TEST_EMBEDDING_ENDPOINT", "https://api.voyageai.com/v1/embeddings"
                ),
            )
            original_embed = voyage.embed

            async def paced_embed(texts, input_type):
                for attempt in range(3):
                    try:
                        return await original_embed(texts, input_type)
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code != 429 or attempt == 2:
                            raise
                        print(
                            "live audit: Voyage rate limit; waiting for provider allowance",
                            flush=True,
                        )
                        await asyncio.sleep(60)

            voyage.embed = paced_embed
            memory = GovernedMemoryAgent(repo, voyage)
            request = MemoryCreate(
                narrative="Fictional CA-to-SG USDC precedent requiring intermediary documentation.",
                route_id="configured-ca-us-sg",
                required_gate="Obtain intermediary documents",
                valid_until=utcnow() + timedelta(days=1),
            )
            included = await memory.create("bank_a", "bank_a:officer", request)
            await memory.create("bank_b", "bank_b:officer", request)
            await memory.create(
                "bank_a", "bank_a:officer", request.model_copy(update={"clearance_level": 2})
            )
            context = adapt_context(scenario_input("corridor_audit"))
            vector = (await voyage.embed([context["narrative"]], "query"))[0]
            deadline = asyncio.get_running_loop().time() + 180
            evidence = None
            while asyncio.get_running_loop().time() < deadline:
                evidence = await memory.retrieve("bank_a", 1, vector, context)
                if evidence["memories"]:
                    break
                await asyncio.sleep(2)
            assert evidence and [m["memory_id"] for m in evidence["memories"]] == [
                included["memory_id"]
            ]
            assert evidence["memory_search_status"] == "complete"
            finding = AuditableActionAgent().assess(context, evidence)
            assert finding["memory_comparison"]["behavior_changed"]
            assert any(g["gate_id"].startswith("memory-") for g in finding["gates"])
            await memory.invalidate(
                "bank_a",
                "bank_a:officer",
                included["memory_id"],
                MemoryInvalidation(expected_version=1, reason="Withdraw incorrect precedent"),
            )
            with pytest.raises(AuditConflict):
                await memory.revalidate("bank_a", 1, evidence)
            # This read must exclude the invalidated memory even while the index lags.
            updated = await memory.retrieve("bank_a", 1, vector, context)
            assert updated["memories"] == []
            assert not AuditableActionAgent().assess(context, updated)["memory_comparison"][
                "behavior_changed"
            ]
            print(
                "live audit: embeddings, isolation, behavior change and invalidation verified",
                flush=True,
            )
    finally:
        await mongo.drop_database(name)
        await mongo.close()
