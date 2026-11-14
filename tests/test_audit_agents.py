from copy import deepcopy
from datetime import timedelta
from io import BytesIO

import httpx
import pytest
from pydantic import ValidationError
from pypdf import PdfReader

from chainlex.audit.agents import AGENT_DESCRIPTIONS, AuditableActionAgent
from chainlex.audit.engine import retry_delay
from chainlex.audit.memory import memory_filter
from chainlex.audit.models import CreateAudit, UnsupportedSchema, digest, utcnow
from chainlex.audit.reports import build_pdf
from chainlex.audit.repository import ledger_event, verify_ledger
from chainlex.audit.scenarios import adapt_context, scenario_input


def evidence(memories=None):
    return {
        "memories": memories or [],
        "regulations": [],
        "memory_search_status": "complete",
        "regulation_search_status": "complete",
        "embedding_model": "voyage-finance-2",
    }


def precedent():
    return {
        "memory_id": "example-memory",
        "version": 1,
        "content_hash": "a" * 64,
        "route_id": "configured-ca-us-sg",
        "required_gate": "Obtain intermediary documents",
        "narrative": "A fictional prior audit required intermediary documents.",
        "valid_until": (utcnow() + timedelta(days=1)).isoformat(),
    }


def snapshot(*, final=False):
    context = adapt_context(scenario_input("corridor_audit"))
    found = evidence([precedent()])
    analysis = AuditableActionAgent().assess(context, found)
    gates = deepcopy(analysis["gates"])
    if final:
        for gate in gates:
            gate.update(
                status="APPROVED",
                actor_id="bank_a:officer",
                decided_at=utcnow().isoformat(),
                decision_reason="Reviewed demo evidence",
            )
    event = ledger_event(
        "bank_a", "audit-test", 1, "AUDIT_REQUESTED", "bank_a:analyst", "0" * 64, {}
    )
    return {
        "audit_id": "audit-test",
        "tenant_id": "bank_a",
        "version": 2 if final else 1,
        "kind": "REVIEWED_FINAL" if final else "DRAFT",
        "verdict": "CONDITIONAL",
        "created_at": utcnow().isoformat(),
        "initiated_by": "bank_a:analyst",
        "analysis_digest": digest(analysis),
        "analysis": analysis,
        "context": context,
        "evidence": found,
        "gates": gates,
        "events": [event],
        "agents": [{"agent_id": a, **d} for a, d in AGENT_DESCRIPTIONS.items()],
    }


def test_three_agents_map_to_problem_statements():
    assert {a["statement"] for a in AGENT_DESCRIPTIONS.values()} == {
        "Agents You Can Audit",
        "Memory You Can Govern",
        "Finish the Job",
    }


def test_audit_cannot_inject_identity_or_state():
    with pytest.raises(ValidationError):
        CreateAudit(idempotency_key="x", tenant_id="victim", state="FINALIZED")


def test_each_bank_and_jurisdiction_has_an_explicit_check():
    context = adapt_context(scenario_input("corridor_audit"))
    result = AuditableActionAgent().assess(context, evidence())
    assert result["recommended_route_id"] == "configured-ca-us-sg"
    assert result["verdict"] == "CONDITIONAL"
    configured = next(r for r in result["routes"] if r["route_id"] == "configured-ca-us-sg")
    assert [r["bank_id"] for r in configured["bank_checks"]] == [
        "scotiabank",
        "jpmorgan_chase",
        "dbs",
    ]
    assert {r["jurisdiction"] for r in configured["jurisdiction_checks"]} == {"CA", "US", "SG"}
    assert all(r["outcome"] == "REVIEW" for r in configured["jurisdiction_checks"])
    assert any(g["gate_id"] == "corridor-verification" for g in result["gates"])


def test_all_denied_routes_produce_no_recommendation():
    result = AuditableActionAgent().assess(
        adapt_context(scenario_input("no_suitable_route")), evidence()
    )
    assert result["recommended_route_id"] is None
    assert result["verdict"] == "NO_SUITABLE_ROUTE"
    assert all(r["outcome"] == "DENY" for r in result["routes"])


def test_policy_block_cannot_be_overridden_by_scripted_finding():
    result = AuditableActionAgent().assess(
        adapt_context(scenario_input("corridor_audit")),
        evidence(),
        blocked_route_ids=("configured-ca-us-sg", "discovered-ca-sg"),
    )
    assert result["recommended_route_id"] is None


def test_memory_changes_checks_and_gates_with_recorded_ablation():
    context = adapt_context(scenario_input("corridor_audit"))
    with_memory = AuditableActionAgent().assess(context, evidence([precedent()]))
    without_memory = AuditableActionAgent().assess(context, evidence())
    comparison = with_memory["memory_comparison"]
    assert comparison["behavior_changed"] is True
    assert comparison["without_memory"]["routes"] == without_memory["routes"]
    assert any(g["gate_id"].startswith("memory-") for g in with_memory["gates"])
    assert comparison["memory_versions"][0]["content_hash"] == "a" * 64


def test_supported_adapter_preserves_semantics_and_unknown_requires_review():
    original = adapt_context(scenario_input("corridor_audit"))
    changed = adapt_context(scenario_input("schema_change"))
    assert original["routes"] == changed["routes"]
    assert "v2" in changed["adapter"]
    with pytest.raises(UnsupportedSchema):
        adapt_context(scenario_input("unsupported_schema"))


def test_memory_filter_enforces_scope_clearance_expiry_and_review():
    now = utcnow()
    query = memory_filter("bank_a", 1, now=now)
    assert query == {
        "tenant_id": "bank_a",
        "scope": "scripted_demo",
        "is_active": True,
        "review_status": "REVIEWED_DEMO",
        "clearance_level": {"$lte": 1},
        "valid_from": {"$lte": now},
        "valid_until": {"$gt": now},
    }


def test_audit_chain_detects_missing_reordered_or_modified_events():
    first = ledger_event("a", "x", 1, "START", "agent", "0" * 64, {})
    second = ledger_event("a", "x", 2, "END", "agent", first["record_hash"], {})
    assert verify_ledger([first, second])
    assert not verify_ledger([second])
    assert not verify_ledger([second, first])
    assert not verify_ledger([first, {**second, "actor_id": "other"}])
    assert not verify_ledger([first], expected_last_hash=second["record_hash"], expected_sequence=2)


def test_provider_retry_after_is_honored_and_bounded():
    request = httpx.Request("POST", "https://example.test/embeddings")
    for header, expected in [("30", 30), ("600", 60), (None, 60)]:
        response = httpx.Response(
            429, request=request, headers={"Retry-After": header} if header else {}
        )
        error = httpx.HTTPStatusError("Rate limited", request=request, response=response)
        assert retry_delay(error, 1) == expected


@pytest.mark.parametrize("final", [False, True])
def test_pdf_contains_routes_evidence_agents_memory_and_human_gates(final):
    report = snapshot(final=final)
    pdf = build_pdf(report)
    reader = PdfReader(BytesIO(pdf))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert len(reader.pages) >= 2
    for required in (
        "SCRIPTED DEMO",
        "configured-ca-us-sg",
        "FINTRAC",
        "Auditable Action Agent",
        "Governed Memory Agent",
        "Durable Completion Agent",
        "example-memory",
        "Human gates",
        report["analysis_digest"],
    ):
        assert required in text
    assert ("REVIEWED_FINAL" if final else "DRAFT") in text
    assert ("APPROVED" if final else "PENDING") in text


def test_pdf_escapes_external_text_and_handles_long_findings():
    report = snapshot()
    report["analysis"]["explanation"] = "<script> & unsupported <b>markup</b> " * 150
    pdf = build_pdf(report)
    text = "\n".join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)
    assert "<script>" in text
