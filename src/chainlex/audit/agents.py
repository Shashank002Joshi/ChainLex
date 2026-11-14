"""Scripted reasoning adapters; policy, memory effects and ranking are executable."""

from chainlex.audit.models import AgentId, HumanGate, digest
from chainlex.domain.routing import (
    AllowlistEntry,
    BankAdmissionPolicy,
    SettlementRoute,
    WalletIdentity,
)
from chainlex.services.route_policy import evaluate_route_admission

AGENT_DESCRIPTIONS = {
    AgentId.ACTION: {"name": "Auditable Action Agent", "statement": "Agents You Can Audit"},
    AgentId.MEMORY: {"name": "Governed Memory Agent", "statement": "Memory You Can Govern"},
    AgentId.COMPLETION: {"name": "Durable Completion Agent", "statement": "Finish the Job"},
}


class AuditableActionAgent:
    agent_id = AgentId.ACTION

    def assess(self, context: dict, evidence: dict, blocked_route_ids=()) -> dict:
        memories = evidence.get("memories", [])
        current = self._rank(context, evidence, memories, blocked_route_ids)
        baseline = self._rank(context, evidence, [], blocked_route_ids)
        gates = [
            HumanGate(
                gate_id="evidence-review",
                title="Review evidence and factual gaps",
                reason="Demo sources are unverified; confirm applicability and missing facts.",
            )
        ]
        if evidence.get("memory_search_status") != "complete":
            gates.append(
                HumanGate(
                    gate_id="memory-availability",
                    title="Review memory availability",
                    reason="Vector Search was unavailable; memory coverage is incomplete.",
                )
            )
        if any(r["provenance"] == "scripted_official_source_candidate" for r in current["routes"]):
            gates.append(
                HumanGate(
                    gate_id="corridor-verification",
                    title="Verify discovered corridor",
                    reason="Official-source fixture references do not establish bank connectivity.",
                )
            )
        for memory in memories:
            gates.append(
                HumanGate(
                    gate_id=f"memory-{memory['memory_id']}-v{memory['version']}",
                    title="Resolve precedent-driven review",
                    reason=memory["required_gate"],
                )
            )
        gates.append(
            HumanGate(
                gate_id="final-signoff",
                title="Final officer sign-off",
                reason="Review the complete audit and all preceding gate decisions.",
            )
        )
        current.update(
            {
                "agent_id": self.agent_id,
                "reasoning_mode": "scripted_demo",
                "fixture_version": context["fixture_version"],
                "finding": "REVIEW_REQUIRED",
                "explanation": "Fictional corridor assessment. Bank admission checks alone do not "
                "establish regulatory clearance; unverified sources remain review issues.",
                "gates": [g.model_dump(mode="json") for g in gates],
                "memory_comparison": {
                    "input_digest": digest(context),
                    "memory_versions": [
                        {
                            "memory_id": m["memory_id"],
                            "version": m["version"],
                            "content_hash": m["content_hash"],
                        }
                        for m in memories
                    ],
                    "without_memory": baseline,
                    "with_memory": {
                        k: current[k] for k in ("recommended_route_id", "verdict", "routes")
                    },
                    "behavior_changed": baseline["routes"] != current["routes"],
                    "interpretation": "Deterministic ablation; this does not prove LLM causality.",
                },
            }
        )
        return current

    def _rank(self, context, evidence, memories, blocked_route_ids):
        results = []
        originator = WalletIdentity(network="simulation", address="0x" + "11" * 20)
        for candidate in context["routes"]:
            route = SettlementRoute(route_id=candidate["route_id"], banks=candidate["banks"])
            # Ephemeral fixture policies are never written as verified bank policies.
            policies = [
                BankAdmissionPolicy(
                    policy_id=f"scripted-{bank.bank_id}",
                    tenant_id="demo-evaluation",
                    version=1,
                    bank_id=bank.bank_id,
                    is_active=True,
                    review_status="VERIFIED",
                    allowed_originators=(AllowlistEntry(wallet=originator),)
                    if context["originator_admitted"]
                    else (),
                )
                for bank in route.banks
            ]
            admission = evaluate_route_admission(route, originator, "demo-evaluation", policies)
            denied = admission["outcome"] == "DENY" or route.route_id in blocked_route_ids
            jurisdictions = []
            issues = ["UNVERIFIED_SOURCE_REFERENCES"]
            for country in route.jurisdictions:
                rules = [r for r in evidence.get("regulations", []) if r["jurisdiction"] == country]
                jurisdictions.append(
                    {
                        "jurisdiction": country,
                        "outcome": "REVIEW",
                        "rule_ids": [r["rule_id"] for r in rules],
                        "reason": "APPLICABILITY_REQUIRES_REVIEW"
                        if rules
                        else "NO_VERIFIED_EVIDENCE",
                    }
                )
            if candidate["provenance"] == "scripted_official_source_candidate":
                issues.extend(["CONNECTIVITY_UNVERIFIED", "CANDIDATE_REQUIRES_HUMAN_VERIFICATION"])
            affected = [m for m in memories if m["route_id"] == route.route_id]
            issues.extend(f"MEMORY_REVIEW:{m['memory_id']}:v{m['version']}" for m in affected)
            if denied:
                issues.append(
                    "BANK_ADMISSION_DENIED"
                    if admission["outcome"] == "DENY"
                    else "ROUTE_BLOCKED_BY_POLICY"
                )
            results.append(
                {
                    "route_id": route.route_id,
                    "provenance": candidate["provenance"],
                    "banks": candidate["banks"],
                    "bank_checks": admission["checks"],
                    "jurisdiction_checks": jurisdictions,
                    "outcome": "DENY" if denied else "CONDITIONAL",
                    "issues": issues,
                    "unresolved_checks": len(issues),
                    "hop_count": len(route.banks) - 1,
                    "policy_provenance": "fictional_in_memory_demo_policies",
                }
            )
        results.sort(
            key=lambda r: (
                r["outcome"] == "DENY",
                r["unresolved_checks"],
                r["hop_count"],
                r["route_id"],
            )
        )
        eligible = [r for r in results if r["outcome"] != "DENY"]
        return {
            "routes": results,
            "recommended_route_id": eligible[0]["route_id"] if eligible else None,
            "verdict": "CONDITIONAL" if eligible else "NO_SUITABLE_ROUTE",
        }
