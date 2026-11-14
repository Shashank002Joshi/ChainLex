"""Multi-Agent Compliance Court: Collaborative Deliberation for Blockchain Transactions.

Implements three distinct agent roles that deliberate on every transaction:
  1. Regulatory Prosecutor Agent: Evaluates statutory non-compliance, missing controls,
     corridor regulations, and argues for immediate protective freeze/review.
  2. Defense Counsel Agent: Evaluates mitigating evidence, regulatory safe harbors,
     de minimis exemptions, verified counterparties, and argues for approval.
  3. Chief Compliance Officer Agent: Authoritative judge who balances prosecutor charges
     against defense arguments, evaluates deterministic policy gates, and issues a binding
     pre-execution verdict.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from chainlex.domain.models import Contract
from chainlex.domain.routing import SettlementRoute
from chainlex.services.country_rules import CaseFacts, Regulation


class AgentRole(StrEnum):
    PROSECUTOR = "REGULATORY_PROSECUTOR"
    DEFENSE_COUNSEL = "DEFENSE_COUNSEL"
    COMPLIANCE_OFFICER = "CHIEF_COMPLIANCE_OFFICER"


class AgentArgument(Contract):
    """Structured submission from a court agent."""

    agent_role: AgentRole
    advocated_verdict: Literal["APPROVE", "REVIEW", "DENY"]
    charges_or_exemptions: tuple[str, ...] = ()
    statutory_citations: tuple[str, ...] = ()
    reasoning_summary: str = Field(min_length=1)
    confidence_score: float = Field(ge=0.0, le=1.0)


class CourtDeliberation(Contract):
    """Complete multi-agent deliberation record."""

    settlement_id: str
    route_summary: str
    prosecutor_submission: AgentArgument
    defense_submission: AgentArgument
    cco_determination: AgentArgument
    final_verdict: Literal["PASS", "REVIEW", "DENY"]
    recommended_action: Literal["CLEAR_SETTLEMENT", "PROTECTIVE_HOLD", "QUARANTINE_REJECT"]
    requires_on_chain_hold: bool


class ProsecutorAgent:
    """Agent 1: Prosecutes regulatory non-compliance, missing disclosures, and breaches."""

    def evaluate(
        self,
        case: CaseFacts,
        regulations: list[Regulation],
        admission_result: dict[str, Any],
        policy_matches: list[dict[str, Any]],
    ) -> AgentArgument:
        charges = []
        citations = []

        # 1. Check admission failures
        if admission_result.get("outcome") == "DENY":
            failed_checks = [
                c for c in admission_result.get("checks", []) if c.get("outcome") == "DENY"
            ]
            for fc in failed_checks:
                charges.append(
                    f"Corridor Hop {fc.get('position', 0)} ({fc.get('bank_id')}): "
                    f"Sender wallet not allowlisted under scope {fc.get('scope')}"
                )

        # 2. Check Sanctions
        if case.sanctions_clear is False:
            charges.append("OFAC/MAS/UN Sanctions List match detected on transaction party")
            citations.append("OFAC-SDN-LIST-500")

        # 3. Check Travel Rule (FATF / FINTRAC / FinCEN)
        if case.travel_rule_complete is False:
            charges.append(
                "FATF Recommendation 16 / Canadian PCMLTFA Travel Rule breach: "
                "Cross-border transfer lacks mandatory originator/beneficiary disclosure payload"
            )
            citations.append("CA-FINTRAC-TRAVEL-001")
            citations.append("FATF-REC-16")

        # 4. Check Customer Due Diligence (MAS PSN02)
        if case.cdd_complete is False:
            charges.append(
                "MAS PSN02 / FinCEN CDD breach: Beneficiary or originator CDD unverified"
            )
            citations.append("SG-MAS-CDD-001")

        # 5. Check Beneficial Ownership / Binance-style commingling
        if case.beneficial_ownership_checked is False:
            charges.append(
                "Unsegregated omnibus transfer: Failure to verify beneficial ownership. "
                "Presents acute commingling and wash-trading risk"
            )
            citations.append("US-BSA-AML-COMMINGLING")

        # Add citations from policy matches
        for m in policy_matches:
            for rid in m.get("source_rule_ids", []):
                if rid not in citations:
                    citations.append(rid)

        if charges:
            is_denial = admission_result.get("outcome") == "DENY" or case.sanctions_clear is False
            advocated = "DENY" if is_denial else "REVIEW"
            corridors = ", ".join(case.applicable_jurisdictions)
            reasoning = (
                f"Regulatory Prosecutor filing {len(charges)} formal charges across "
                f"jurisdictions {corridors}. Transaction demonstrates acute compliance deficits."
            )
            confidence = 0.95
        else:
            advocated = "APPROVE"
            reasoning = "Prosecutor review reveals no statutory violations or missing controls."
            confidence = 0.88

        return AgentArgument(
            agent_role=AgentRole.PROSECUTOR,
            advocated_verdict=advocated,
            charges_or_exemptions=tuple(charges),
            statutory_citations=tuple(citations),
            reasoning_summary=reasoning,
            confidence_score=confidence,
        )


class DefenseCounselAgent:
    """Agent 2: Defends transaction safe harbors, exemptions, and compliance proofs."""

    def evaluate(
        self,
        case: CaseFacts,
        regulations: list[Regulation],
        admission_result: dict[str, Any],
    ) -> AgentArgument:
        exemptions = []
        citations = []

        if case.sanctions_clear is True:
            exemptions.append("Sanctions screening is fully CLEAR across global databases")
        if case.cdd_complete is True:
            exemptions.append("Full Tier-1 Customer Due Diligence (KYC) documentation on file")
        if case.travel_rule_complete is True:
            exemptions.append("Off-chain Travel Rule commitment verified via instructions hash")
        if case.beneficial_ownership_checked is True:
            exemptions.append("Beneficial ownership established and segregated from omnibus pool")

        if admission_result.get("outcome") == "PASS":
            exemptions.append(
                "All corridor correspondent banks verified originator institutional identity"
            )

        if admission_result.get("outcome") == "DENY":
            advocated = "REVIEW"
            reasoning = (
                "Defense acknowledges admission gate failure, but argues this may represent "
                "an operational key rotation delay. Requests manual officer escalation."
            )
            confidence = 0.65
        elif not case.travel_rule_complete:
            advocated = "REVIEW"
            reasoning = (
                "Defense notes high-trust institutional relationship between counterparties; "
                "submits that missing Travel Rule metadata can be cured via secondary outbox relay."
            )
            confidence = 0.72
        else:
            advocated = "APPROVE"
            reasoning = (
                "Defense demonstrates full satisfaction of statutory safe harbors and "
                "correspondent bank admission criteria. Transaction should proceed unimpeded."
            )
            confidence = 0.94

        return AgentArgument(
            agent_role=AgentRole.DEFENSE_COUNSEL,
            advocated_verdict=advocated,
            charges_or_exemptions=tuple(exemptions),
            statutory_citations=tuple(citations),
            reasoning_summary=reasoning,
            confidence_score=confidence,
        )


class ComplianceOfficerAgent:
    """Agent 3: Authoritative Judge and Chief Compliance Officer presiding over the court."""

    def adjudicate(
        self,
        settlement_id: str,
        route: SettlementRoute,
        prosecutor_sub: AgentArgument,
        defense_sub: AgentArgument,
        admission_outcome: str,
        policy_outcome: str,
    ) -> CourtDeliberation:
        if admission_outcome == "DENY" or prosecutor_sub.advocated_verdict == "DENY":
            final_verdict = "DENY"
            recommended_action = "QUARANTINE_REJECT"
            requires_hold = True
            reasoning = (
                "Chief Compliance Officer Verdict: DENIAL AND IMMEDIATE QUARANTINE. "
                "Defense argument overruled. Bank admission failure or sanctions flag "
                "constitutes a critical regulatory boundary. Dispatched on-chain hold."
            )
            confidence = 0.99
        elif policy_outcome == "REVIEW" or prosecutor_sub.advocated_verdict == "REVIEW":
            final_verdict = "REVIEW"
            recommended_action = "PROTECTIVE_HOLD"
            requires_hold = True
            count = len(prosecutor_sub.charges_or_exemptions)
            reasoning = (
                f"Chief Compliance Officer Verdict: STATUTORY REVIEW REQUIRED. "
                f"Prosecutor established {count} unfulfilled statutory controls. "
                "Pre-execution policy mandates automated on-chain protective hold."
            )
            confidence = 0.95
        else:
            final_verdict = "PASS"
            recommended_action = "CLEAR_SETTLEMENT"
            requires_hold = False
            reasoning = (
                "Chief Compliance Officer Verdict: FULL STATUTORY CLEARANCE. "
                "Defense arguments sustained. All compliance controls (FINTRAC, OFAC, MAS) "
                "and admission policies satisfied. Transaction cleared for atomic settlement."
            )
            confidence = 0.98

        cco_sub = AgentArgument(
            agent_role=AgentRole.COMPLIANCE_OFFICER,
            advocated_verdict="APPROVE" if final_verdict == "PASS" else final_verdict,
            charges_or_exemptions=(f"Final binding determination: {final_verdict}",),
            statutory_citations=prosecutor_sub.statutory_citations,
            reasoning_summary=reasoning,
            confidence_score=confidence,
        )

        return CourtDeliberation(
            settlement_id=settlement_id,
            route_summary=route.narrative(),
            prosecutor_submission=prosecutor_sub,
            defense_submission=defense_sub,
            cco_determination=cco_sub,
            final_verdict=final_verdict,
            recommended_action=recommended_action,
            requires_on_chain_hold=requires_hold,
        )


class ComplianceCourt:
    """Coordinates the 3-agent deliberative court for any transaction."""

    def __init__(self):
        self.prosecutor = ProsecutorAgent()
        self.defense = DefenseCounselAgent()
        self.cco = ComplianceOfficerAgent()

    def deliberate(
        self,
        settlement_id: str,
        route: SettlementRoute,
        case: CaseFacts,
        regulations: list[Regulation],
        admission_result: dict[str, Any],
        policy_result: dict[str, Any],
    ) -> CourtDeliberation:
        pros_sub = self.prosecutor.evaluate(
            case=case,
            regulations=regulations,
            admission_result=admission_result,
            policy_matches=policy_result.get("matches", []),
        )

        def_sub = self.defense.evaluate(
            case=case,
            regulations=regulations,
            admission_result=admission_result,
        )

        deliberation = self.cco.adjudicate(
            settlement_id=settlement_id,
            route=route,
            prosecutor_sub=pros_sub,
            defense_sub=def_sub,
            admission_outcome=admission_result.get("outcome", "DENY"),
            policy_outcome=policy_result.get("outcome", "REVIEW"),
        )

        return deliberation
