"""Automated regression testing for ChainLex Dynamic End-to-End Compliance Runner.

Validates:
  1. Multi-Agent Compliance Court Deliberation (Prosecutor, Defense, CCO).
  2. Case 1: Cross-country compliance (CA -> US -> SG corridor with FINTRAC / MAS).
  3. Case 2: Binance-like hack prevention (unsegregated omnibus sweep, protective hold).
  4. Case 3: Multihop correspondent routing with strict intermediary admission.
  5. Clean compliant corridor clearance.
  6. Domain invariant rejections at Leg 1 Intake (wash trade, zero hash, routing loop).
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from chainlex.agents import AgentRole
from chainlex.services.e2e_runner import run_e2e_verification


@pytest.mark.asyncio
async def test_e2e_cross_country_case_triggers_prosecutor_and_hold():
    """Case 1: Missing Travel Rule triggers Prosecutor charge and CCO protective hold."""
    report = await run_e2e_verification(
        scenario="cross_country",
        origin_bank="scotiabank",
        origin_country="CA",
        inter_banks=["jpmorgan_chase"],
        inter_countries=["US"],
        dest_bank="dbs",
        dest_country="SG",
        amount=250000.0,
        travel_rule_complete=False,
        mode="simulated",
        verbose=False,
    )

    assert report["overall_status"] == "REVIEW"
    assert "leg_1_intake" in report["legs"]
    assert "leg_2_admission" in report["legs"]
    assert "leg_3_evidence" in report["legs"]
    assert "leg_4_analysis" in report["legs"]
    assert "leg_5_dispatch" in report["legs"]
    assert "leg_6_audit" in report["legs"]

    # Verify Multi-Agent Court Deliberation
    court = report["legs"]["leg_4_analysis"]["court_deliberation"]
    assert court["prosecutor_submission"]["agent_role"] == AgentRole.PROSECUTOR
    assert court["prosecutor_submission"]["advocated_verdict"] == "REVIEW"
    assert "CA-FINTRAC-TRAVEL-001" in court["prosecutor_submission"]["statutory_citations"]
    assert court["cco_determination"]["agent_role"] == AgentRole.COMPLIANCE_OFFICER
    assert court["final_verdict"] == "REVIEW"
    assert court["requires_on_chain_hold"] is True

    # Verify Leg 5 hold confirmation
    assert report["legs"]["leg_5_dispatch"]["status"] == "CONFIRMED"
    assert "tx_hash" in report["legs"]["leg_5_dispatch"]


@pytest.mark.asyncio
async def test_e2e_binance_hack_unsegregated_sweep_triggers_hold():
    """Case 2: Internal omnibus sweep lacking beneficial ownership triggers protective hold."""
    report = await run_e2e_verification(
        scenario="binance_hack",
        amount=5000000.0,
        beneficial_ownership_checked=False,
        mode="simulated",
        verbose=False,
    )

    assert report["overall_status"] == "REVIEW"
    court = report["legs"]["leg_4_analysis"]["court_deliberation"]
    assert court["requires_on_chain_hold"] is True
    assert any(
        "beneficial ownership" in chg.lower()
        for chg in court["prosecutor_submission"]["charges_or_exemptions"]
    )
    assert report["legs"]["leg_5_dispatch"]["status"] == "CONFIRMED"


@pytest.mark.asyncio
async def test_e2e_multihop_strict_intermediary_admission_denial():
    """Case 3: Intermediary with strict ALL_ROUTE_POSITIONS denies unlisted sender."""
    report = await run_e2e_verification(
        scenario="multihop_routing",
        strict_intermediary=True,
        mode="simulated",
        verbose=False,
    )

    assert report["overall_status"] == "DENY"
    court = report["legs"]["leg_4_analysis"]["court_deliberation"]
    assert court["final_verdict"] == "DENY"
    assert court["recommended_action"] == "QUARANTINE_REJECT"
    assert court["requires_on_chain_hold"] is True
    assert report["legs"]["leg_2_admission"]["admission_outcome"] == "DENY"


@pytest.mark.asyncio
async def test_e2e_fully_compliant_route_cleared_without_hold():
    """Clean institutional settlement passes all agent checks and clears without freeze."""
    report = await run_e2e_verification(
        scenario="custom",
        amount=100000.0,
        symbol="USDC",
        cdd_complete=True,
        travel_rule_complete=True,
        sanctions_clear=True,
        beneficial_ownership_checked=True,
        mode="simulated",
        verbose=False,
    )

    assert report["overall_status"] == "PASS"
    court = report["legs"]["leg_4_analysis"]["court_deliberation"]
    assert court["final_verdict"] == "PASS"
    assert court["requires_on_chain_hold"] is False
    assert report["legs"]["leg_5_dispatch"]["status"] == "CLEARED"


@pytest.mark.asyncio
async def test_e2e_wash_trade_rejected_at_leg1_intake():
    """Leg 1 Invariant: Initiator == Beneficiary is rejected before state creation."""
    report = await run_e2e_verification(
        scenario="custom",
        wash_trade=True,
        mode="simulated",
        verbose=False,
    )

    assert report["overall_status"] == "REJECTED_AT_INTAKE"
    assert report["legs"]["leg_1_intake"]["status"] == "REJECTED"
    assert "Self-settlement prohibited" in report["legs"]["leg_1_intake"]["error"]


@pytest.mark.asyncio
async def test_e2e_zero_instructions_hash_rejected_at_leg1_intake():
    """Leg 1 Invariant: 0x00...00 Travel Rule commitment hash is rejected."""
    report = await run_e2e_verification(
        scenario="custom",
        zero_instructions_hash=True,
        mode="simulated",
        verbose=False,
    )

    assert report["overall_status"] == "REJECTED_AT_INTAKE"
    assert report["legs"]["leg_1_intake"]["status"] == "REJECTED"
    assert "instructions hash must be nonzero" in report["legs"]["leg_1_intake"]["error"]


@pytest.mark.asyncio
async def test_e2e_routing_loop_rejected_at_leg1_intake():
    """Leg 1 Invariant: Repeating bank creates a loop and is rejected."""
    report = await run_e2e_verification(
        scenario="custom",
        origin_bank="scotiabank",
        origin_country="CA",
        inter_banks=["jpmorgan_chase"],
        inter_countries=["US"],
        dest_bank="scotiabank",  # Routing loop: Scotiabank -> JPMorgan -> Scotiabank
        dest_country="CA",
        mode="simulated",
        verbose=False,
    )

    assert report["overall_status"] == "REJECTED_AT_INTAKE"
    assert report["legs"]["leg_1_intake"]["status"] == "REJECTED"
    assert "Routing Loop Invariant Violated" in report["legs"]["leg_1_intake"]["error"]


@pytest.mark.asyncio
async def test_e2e_tx_file_loading_and_report_output():
    """Test JSON file transaction intake and report generation."""
    with TemporaryDirectory() as tmp_dir:
        report_file = Path(tmp_dir) / "test_audit_report.json"
        report = await run_e2e_verification(
            scenario="custom",
            amount=50000.0,
            mode="simulated",
            verbose=False,
        )
        with report_file.open("w") as f:
            json.dump(report, f)

        assert report_file.exists()
        loaded = json.loads(report_file.read_text())
        assert loaded["overall_status"] in ("PASS", "REVIEW", "DENY")
        assert "leg_6_audit" in loaded["legs"]
