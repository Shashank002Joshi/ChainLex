"""Country corpus, deterministic review policies, and governed Voyage retrieval."""

import hashlib
import math
from datetime import UTC, datetime
from typing import Literal

import httpx
from pydantic import Field, HttpUrl

from chainlex.domain.models import Contract

Country = Literal["SG", "CA", "US"]
ControlFact = Literal[
    "cdd_complete",
    "travel_rule_complete",
    "sanctions_clear",
    "monitoring_review_complete",
    "recordkeeping_complete",
    "reporting_review_complete",
    "licensing_review_complete",
    "risk_assessment_complete",
    "beneficial_ownership_checked",
]


class Regulation(Contract):
    rule_id: str
    jurisdiction: Country
    regulator: str
    title: str
    section: str
    rule_text: str
    source_url: HttpUrl
    retrieved_at: str
    topics: tuple[str, ...] = ()
    applicability_notes: str = ""
    example_query: str = ""
    source_kind: Literal["NOTICE_OVERVIEW", "GUIDANCE"] = "GUIDANCE"
    review_status: Literal["UNVERIFIED", "VERIFIED"] = "UNVERIFIED"
    # Corpus summaries have no independently verified legal effective date.
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    def embedding_text(self) -> str:
        return (
            f"Jurisdiction: {self.jurisdiction}\nRegulator: {self.regulator}\n"
            f"Title: {self.title}\nSection: {self.section}\n"
            f"Topics: {', '.join(self.topics)}\nApplies to: {self.applicability_notes}\n"
            f"Rule: {self.rule_text}"
        )


class ReviewPolicy(Contract):
    policy_id: str
    jurisdiction: Country
    source_rule_ids: tuple[str, ...]
    required_fact: ControlFact
    description: str
    version: int = Field(default=1, ge=1)
    outcome: Literal["REVIEW"] = "REVIEW"
    policy_type: Literal["INTERNAL_DEMO"] = "INTERNAL_DEMO"


class CaseFacts(Contract):
    jurisdictions: tuple[Country, ...] = Field(min_length=1)
    entity_type: str
    transaction_type: str
    narrative: str = Field(min_length=1, max_length=10000)
    cdd_complete: bool | None = None
    travel_rule_complete: bool | None = None
    sanctions_clear: bool | None = None
    monitoring_review_complete: bool | None = None
    recordkeeping_complete: bool | None = None
    reporting_review_complete: bool | None = None
    licensing_review_complete: bool | None = None
    risk_assessment_complete: bool | None = None
    beneficial_ownership_checked: bool | None = None

    def query_text(self) -> str:
        return (
            f"Jurisdictions: {', '.join(self.jurisdictions)}. Entity: {self.entity_type}. "
            f"Transaction: {self.transaction_type}. {self.narrative}. "
            f"CDD complete: {self.cdd_complete}; Travel Rule complete: "
            f"{self.travel_rule_complete}; sanctions clear: {self.sanctions_clear}. "
            "Find applicable AML/CFT, transfer information and sanctions guidance."
        )


def evaluate_policies(case: CaseFacts, policies: list[ReviewPolicy]) -> dict:
    """Unknown facts fail to review. No matching policy never implies approval."""
    matches = []
    for policy in policies:
        if policy.jurisdiction in case.jurisdictions:
            value = getattr(case, policy.required_fact)
            if value is not True:
                matches.append(
                    {
                        "policy_id": policy.policy_id,
                        "policy_version": policy.version,
                        "source_rule_ids": list(policy.source_rule_ids),
                        "reason": "MISSING_FACT" if value is None else "CONTROL_NOT_SATISFIED",
                    }
                )
    return {"outcome": "REVIEW" if matches else "NO_MATCH", "matches": matches}


class VoyageEmbeddings:
    """Explicit endpoint supports Atlas and legacy Voyage keys; no implicit key routing."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        endpoint: str = "https://ai.mongodb.com/v1/embeddings",
    ):
        if not api_key:
            raise ValueError("CHAINLEX_VOYAGE_API_KEY is required")
        if endpoint not in {
            "https://ai.mongodb.com/v1/embeddings",
            "https://api.voyageai.com/v1/embeddings",
        }:
            raise ValueError("Unsupported Voyage endpoint")
        self.client, self.api_key, self.endpoint = client, api_key, endpoint

    async def embed(self, texts: list[str], input_type: Literal["document", "query"]):
        response = await self.client.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"input": texts, "model": "voyage-finance-2", "input_type": input_type},
        )
        response.raise_for_status()
        data = sorted(response.json()["data"], key=lambda item: item["index"])
        if [item["index"] for item in data] != list(range(len(texts))):
            raise ValueError("Embedding response count/index mismatch")
        vectors = [item["embedding"] for item in data]
        for vector in vectors:
            if len(vector) != 1024 or not all(
                type(value) in (int, float) and math.isfinite(value) for value in vector
            ):
                raise ValueError("Expected 1024 finite numeric dimensions")
        return vectors


async def ingest_rules(db, voyage: VoyageEmbeddings, rules: list[Regulation], tenant_id: str):
    """Insert immutable content versions; do not overwrite an officer's later review."""
    texts = [rule.embedding_text() for rule in rules]
    vectors = await voyage.embed(texts, "document")
    for rule, text, vector in zip(rules, texts, vectors, strict=True):
        digest = hashlib.sha256(text.encode()).hexdigest()
        document = rule.model_dump(mode="python")
        document.update(
            {
                "_id": f"{tenant_id}:{rule.rule_id}:{digest}",
                "source_url": str(rule.source_url),
                "tenant_id": tenant_id,
                "schema_version": 1,
                "is_active": True,
                "clearance_level": 1,
                "text_hash": digest,
                "embedding": vector,
                "embedding_model": "voyage-finance-2",
                "embedding_version": 1,
            }
        )
        await db.regulations.update_one(
            {"_id": document["_id"]}, {"$setOnInsert": document}, upsert=True
        )


def retrieval_pipeline(
    case: CaseFacts,
    vector: list[float],
    tenant_id: str,
    clearance: int,
    now: datetime,
    limit: int = 3,
):
    if not tenant_id or clearance < 1 or not 1 <= limit <= 20:
        raise ValueError("Invalid retrieval scope")
    return [
        {
            "$vectorSearch": {
                "index": "regulations_vector_idx",
                "path": "embedding",
                "queryVector": vector,
                "numCandidates": 100,
                "limit": limit,
                "filter": {
                    "$and": [
                        {"tenant_id": {"$eq": tenant_id}},
                        {"jurisdiction": {"$in": list(case.jurisdictions)}},
                        {"review_status": {"$eq": "VERIFIED"}},
                        {"is_active": {"$eq": True}},
                        {"clearance_level": {"$lte": clearance}},
                        {"valid_from": {"$lte": now}},
                        {"$or": [{"valid_until": {"$eq": None}}, {"valid_until": {"$gt": now}}]},
                    ]
                },
            }
        },
        {
            "$project": {
                "embedding": 0,
            }
        },
        {"$set": {"vector_score": {"$meta": "vectorSearchScore"}}},
    ]


async def retrieve_rules(
    db, voyage: VoyageEmbeddings, case: CaseFacts, tenant_id: str, clearance: int
):
    vector = (await voyage.embed([case.query_text()], "query"))[0]
    cursor = db.regulations.aggregate(
        retrieval_pipeline(case, vector, tenant_id, clearance, datetime.now(UTC))
    )
    cursor = await cursor
    return [document async for document in cursor]
