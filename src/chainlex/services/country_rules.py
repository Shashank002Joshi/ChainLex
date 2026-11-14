"""Country corpus, deterministic review policies, and governed Voyage retrieval."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, HttpUrl, model_validator

from chainlex.domain.models import Contract
from chainlex.domain.routing import Country, SettlementRoute
from chainlex.services.embeddings import (
    VoyageEmbeddings,
    embedding_metadata,
    has_current_embedding,
    text_hash,
    validate_vector,
)

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
    jurisdictions: tuple[Country, ...] = ()
    route: SettlementRoute | None = None
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

    @model_validator(mode="after")
    def require_geography(self):
        if not self.jurisdictions and self.route is None:
            raise ValueError("Provide jurisdictions or a settlement route")
        return self

    @property
    def applicable_jurisdictions(self) -> tuple[Country, ...]:
        route_countries = self.route.jurisdictions if self.route else ()
        return tuple(dict.fromkeys((*self.jurisdictions, *route_countries)))

    def query_text(self) -> str:
        return (
            f"Jurisdictions: {', '.join(self.applicable_jurisdictions)}. "
            f"Route: {self.route.narrative() if self.route else 'not supplied'}. "
            f"Entity: {self.entity_type}. "
            f"Transaction: {self.transaction_type}. {self.narrative}. "
            f"CDD complete: {self.cdd_complete}; Travel Rule complete: "
            f"{self.travel_rule_complete}; sanctions clear: {self.sanctions_clear}. "
            "Find applicable AML/CFT, transfer information and sanctions guidance."
        )


def evaluate_policies(case: CaseFacts, policies: list[ReviewPolicy]) -> dict:
    """Unknown facts fail to review. No matching policy never implies approval."""
    matches = []
    for policy in policies:
        if policy.jurisdiction in case.applicable_jurisdictions:
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


async def ingest_rules(db, voyage: VoyageEmbeddings, rules: list[Regulation], tenant_id: str):
    """Insert immutable content versions; do not overwrite an officer's later review."""
    if not tenant_id:
        raise ValueError("Tenant is required")
    pending = {}
    for rule in rules:
        text = rule.embedding_text()
        key = f"{tenant_id}:{rule.rule_id}:{text_hash(text)}"
        existing = await db.regulations.find_one({"_id": key, "tenant_id": tenant_id})
        if existing is not None:
            if not has_current_embedding(existing, text):
                raise ValueError("Stored regulation embedding needs explicit repair or migration")
            continue
        pending[key] = (rule, text)
    if not pending:
        return
    vectors = await voyage.embed([text for _, text in pending.values()], "document")
    for (key, (rule, text)), vector in zip(pending.items(), vectors, strict=True):
        document = rule.model_dump(mode="python")
        document.update(
            {
                "_id": key,
                "source_url": str(rule.source_url),
                "tenant_id": tenant_id,
                "schema_version": 1,
                "is_active": True,
                "clearance_level": 1,
                "embedding": vector,
                **embedding_metadata(text),
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
    validate_vector(vector)
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
                        {"jurisdiction": {"$in": list(case.applicable_jurisdictions)}},
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
    # Route cases reserve a result budget for each country. A single global top-3
    # could otherwise omit an intermediary's regulations entirely.
    cases = [case]
    if case.route is not None:
        cases = [
            case.model_copy(
                update={
                    "route": None,
                    "jurisdictions": (country,),
                    "narrative": f"{case.narrative}. Full route: {case.route.narrative()}",
                }
            )
            for country in case.applicable_jurisdictions
        ]
    vectors = await voyage.embed([item.query_text() for item in cases], "query")
    now = datetime.now(UTC)
    results = []
    for item, vector in zip(cases, vectors, strict=True):
        cursor = await db.regulations.aggregate(
            retrieval_pipeline(item, vector, tenant_id, clearance, now)
        )
        results.extend([document async for document in cursor])
    return results
