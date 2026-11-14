"""Governed memory retrieval and versioned officer-approved corrections."""

from datetime import timedelta
from uuid import uuid4

from pymongo.errors import OperationFailure

from chainlex.audit.models import (
    ActionDenied,
    AgentId,
    AuditConflict,
    AuditNotFound,
    EmbeddingUnavailable,
    MemoryCreate,
    MemoryInvalidation,
    WorkflowPaused,
    digest,
    utcnow,
)
from chainlex.services.country_rules import CaseFacts, retrieval_pipeline
from chainlex.services.embeddings import EMBEDDING_MODEL, embedding_metadata, validate_vector


class MemoryIndexPending(RuntimeError):
    """A newly inserted demo memory has not reached the Vector Search index yet."""


def memory_filter(tenant: str, clearance: int, *, now=None):
    now = now or utcnow()
    return {
        "tenant_id": tenant,
        "scope": "scripted_demo",
        "is_active": True,
        "review_status": "REVIEWED_DEMO",
        "clearance_level": {"$lte": clearance},
        "valid_from": {"$lte": now},
        "valid_until": {"$gt": now},
    }


async def index_ready(collection, name):
    try:
        indexes = [i async for i in await collection.list_search_indexes()]
        return any(i["name"] == name and i.get("queryable") for i in indexes)
    except OperationFailure as exc:
        if exc.code not in {13, 26, 59, 115, 8000}:
            raise
        return False


def eligible_memory(doc, tenant, clearance, *, now=None):
    now = now or utcnow()
    return (
        doc.get("tenant_id") == tenant
        and doc.get("scope") == "scripted_demo"
        and doc.get("is_active") is True
        and doc.get("review_status") == "REVIEWED_DEMO"
        and doc.get("clearance_level", 99) <= clearance
        and doc.get("valid_from") is not None
        and doc["valid_from"] <= now
        and doc.get("valid_until") is not None
        and doc["valid_until"] > now
    )


class GovernedMemoryAgent:
    agent_id = AgentId.MEMORY

    def __init__(self, repository, voyage):
        self.repo, self.db, self.voyage = repository, repository.db, voyage

    async def retrieve(self, tenant, clearance, vector, context):
        validate_vector(vector)
        records, rules = [], []
        status, rule_status = "complete", "complete"
        memory_ready = await index_ready(self.db.audit_memories, "audit_memories_idx")
        rules_ready = await index_ready(self.db.regulations, "regulations_vector_idx")
        if not memory_ready:
            status = "unavailable"
        if not rules_ready:
            rule_status = "unavailable"
        try:
            hits = []
            if memory_ready:
                cursor = await self.db.audit_memories.aggregate(
                    [
                        {
                            "$vectorSearch": {
                                "index": "audit_memories_idx",
                                "path": "case_embedding",
                                "queryVector": vector,
                                "numCandidates": 100,
                                "limit": 20,
                                "filter": memory_filter(tenant, clearance),
                            }
                        },
                        {"$project": {"_id": 1, "score": {"$meta": "vectorSearchScore"}}},
                    ]
                )
                hits = [hit async for hit in cursor]
            for hit in hits:
                # Index results can lag invalidation/expiry: read the authoritative version.
                doc = await self.db.audit_memories.find_one(
                    {"_id": hit["_id"], **memory_filter(tenant, clearance)},
                    {"_id": 0, "case_embedding": 0},
                )
                if doc:
                    records.append({**doc, "relevance_score": hit["score"]})
        except OperationFailure as exc:
            if exc.code not in {27, 26, 40324, 31082, 40602, 8000}:
                raise
            status = "unavailable"
        countries = list(
            dict.fromkeys(b["jurisdiction"] for r in context["routes"] for b in r["banks"])
        )
        try:
            for country in countries if rules_ready else []:
                case = CaseFacts(
                    jurisdictions=(country,),
                    entity_type="DEMO_INSTITUTION",
                    transaction_type="AUDIT",
                    narrative=context["narrative"],
                )
                cursor = await self.db.regulations.aggregate(
                    retrieval_pipeline(case, vector, tenant, clearance, utcnow())
                )
                async for hit in cursor:
                    doc = await self.db.regulations.find_one(
                        {
                            "_id": hit["_id"],
                            "tenant_id": tenant,
                            "is_active": True,
                            "review_status": "VERIFIED",
                            "clearance_level": {"$lte": clearance},
                            "valid_from": {"$lte": utcnow()},
                            "$or": [{"valid_until": None}, {"valid_until": {"$gt": utcnow()}}],
                        },
                        {"_id": 0, "embedding": 0},
                    )
                    if doc:
                        rules.append(doc)
        except OperationFailure as exc:
            if exc.code not in {27, 26, 40324, 31082, 40602, 8000}:
                raise
            rule_status = "unavailable"
        return {
            "memories": records,
            "regulations": rules,
            "memory_search_status": status,
            "regulation_search_status": rule_status,
            "embedding_model": EMBEDDING_MODEL,
            "scope": "scripted_demo",
        }

    async def revalidate(self, tenant, clearance, evidence, *, session=None):
        for reference in evidence.get("memories", []):
            current = await self.db.audit_memories.find_one(
                {
                    "memory_id": reference["memory_id"],
                    "version": reference["version"],
                    "content_hash": reference["content_hash"],
                    **memory_filter(tenant, clearance),
                },
                session=session,
            )
            if current is None:
                raise AuditConflict("A referenced memory was corrected, invalidated or expired")
        for reference in evidence.get("regulations", []):
            current = await self.db.regulations.find_one(
                {
                    "tenant_id": tenant,
                    "rule_id": reference["rule_id"],
                    "text_hash": reference["text_hash"],
                    "is_active": True,
                    "review_status": "VERIFIED",
                    "clearance_level": {"$lte": clearance},
                    "valid_from": {"$lte": utcnow()},
                    "$or": [{"valid_until": None}, {"valid_until": {"$gt": utcnow()}}],
                },
                session=session,
            )
            if current is None:
                raise AuditConflict("A referenced regulation changed or expired")

    async def embedding_permit(self, tenant, actor):
        async def check(session, control):
            if control["paused"]:
                raise WorkflowPaused("Tenant is paused")
            policy = await self.repo.policy(tenant, session=session)
            identity = await self.db.agent_identities.find_one(
                {"tenant_id": tenant, "agent_id": AgentId.MEMORY, "is_active": True},
                session=session,
            )
            if not identity or "EMBED_MEMORY" not in policy["allowed_actions"].get(
                AgentId.MEMORY, []
            ):
                raise ActionDenied("MEMORY_EMBEDDING_NOT_PERMITTED")
            await self.db.agent_identities.update_one(
                {"_id": identity["_id"], "is_active": True},
                {"$inc": {"permit_serial": 1}},
                session=session,
            )

        await self.repo.governance(
            tenant,
            actor,
            "MEMORY_EMBEDDING_PERMITTED",
            {"agent_id": AgentId.MEMORY},
            check,
            bump=False,
        )

    async def create(self, tenant, actor, request: MemoryCreate, *, memory_id=None, previous=None):
        if request.valid_until <= utcnow():
            raise ValueError("Memory expiry must be in the future")
        if self.voyage is None:
            raise EmbeddingUnavailable("Voyage is not configured")
        await self.embedding_permit(tenant, actor)
        vector = (await self.voyage.embed([request.narrative], "document"))[0]
        validate_vector(vector)
        identity = memory_id or "memory-" + uuid4().hex
        version = previous["version"] + 1 if previous else 1
        doc = {
            "_id": f"{tenant}:{identity}:v{version}",
            "memory_id": identity,
            "tenant_id": tenant,
            "schema_version": 1,
            "version": version,
            **request.model_dump(mode="python", exclude={"expected_version", "reason"}),
            "scope": "scripted_demo",
            "review_status": "REVIEWED_DEMO",
            "is_active": True,
            "is_demo_fixture": True,
            "approved_by": actor,
            "valid_from": utcnow(),
            "case_embedding": vector,
            **embedding_metadata(request.narrative),
        }
        doc["content_hash"] = digest(
            {k: v for k, v in doc.items() if k not in {"_id", "case_embedding"}}
        )

        async def save(session, control):
            if previous:
                result = await self.db.audit_memories.update_one(
                    {
                        "_id": previous["_id"],
                        "tenant_id": tenant,
                        "version": previous["version"],
                        "is_active": True,
                    },
                    {
                        "$set": {
                            "is_active": False,
                            "replaced_by": doc["_id"],
                            "correction_reason": request.reason,
                        }
                    },
                    session=session,
                )
                if result.modified_count != 1:
                    raise AuditConflict("Memory version changed")
            await self.db.audit_memories.insert_one(dict(doc), session=session)

        await self.repo.governance(
            tenant,
            actor,
            "MEMORY_CORRECTED" if previous else "MEMORY_CREATED",
            {
                "memory_id": identity,
                "version": version,
                "content_hash": doc["content_hash"],
                "reason": getattr(request, "reason", "Officer-approved demo memory"),
            },
            save,
        )
        return {k: v for k, v in doc.items() if k not in {"_id", "case_embedding"}}

    async def get(self, tenant, memory_id, clearance=2):
        doc = await self.db.audit_memories.find_one(
            {"tenant_id": tenant, "memory_id": memory_id, "clearance_level": {"$lte": clearance}},
            sort=[("version", -1)],
        )
        if doc is None:
            raise AuditNotFound("Memory not found")
        return doc

    async def correct(self, tenant, actor, memory_id, request):
        previous = await self.get(tenant, memory_id)
        if previous["version"] != request.expected_version or not previous["is_active"]:
            raise AuditConflict("Memory version changed or is inactive")
        return await self.create(tenant, actor, request, memory_id=memory_id, previous=previous)

    async def invalidate(self, tenant, actor, memory_id, request: MemoryInvalidation):
        async def remove(session, control):
            result = await self.db.audit_memories.update_one(
                {
                    "tenant_id": tenant,
                    "memory_id": memory_id,
                    "version": request.expected_version,
                    "is_active": True,
                },
                {
                    "$set": {
                        "is_active": False,
                        "invalidated_by": actor,
                        "invalidated_at": utcnow(),
                        "invalidation_reason": request.reason,
                    }
                },
                session=session,
            )
            if result.modified_count != 1:
                raise AuditConflict("Memory version changed or is inactive")

        await self.get(tenant, memory_id)
        await self.repo.governance(
            tenant, actor, "MEMORY_INVALIDATED", request.model_dump(), remove
        )
        return {"memory_id": memory_id, "status": "INVALIDATED"}

    async def ensure_demo(self, tenant):
        identity = "demo-intermediary-review"
        existing = await self.db.audit_memories.find_one(
            {"tenant_id": tenant, "memory_id": identity}, sort=[("version", -1)]
        )
        if existing:
            return existing
        # Fixture review applies only to the isolated scripted-demo scope.
        request = MemoryCreate(
            narrative="Fictional CA-US-SG corridor precedent: obtain enhanced intermediary "
            "documentation before recommending configured-ca-us-sg.",
            route_id="configured-ca-us-sg",
            required_gate="Obtain enhanced intermediary documentation",
            valid_until=utcnow() + timedelta(days=30),
        )
        return await self.create(tenant, "demo-fixture-loader", request, memory_id=identity)
