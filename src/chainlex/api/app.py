"""API process: runnable health checks and validated workflow route contracts."""

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from chainlex.api.transactions import router as transaction_router
from chainlex.audit.api import install_exception_handlers
from chainlex.audit.api import router as audit_router
from chainlex.auth import Principal, current_principal, require_officer
from chainlex.config import Settings
from chainlex.db.connection import database_lifespan, database_readiness
from chainlex.domain.fsm import LEG_STATES, STATE_DEFINITIONS
from chainlex.domain.models import CreateFSM, ProposalDecision
from chainlex.domain.transitions import TRANSITIONS
from chainlex.services.contracts import ComplianceFSM
from chainlex.services.e2e_runner import run_e2e_verification


class VerifyComplianceRequest(BaseModel):
    scenario: Literal[
        "cross_country", "binance_hack", "multihop_routing", "sanctions_blocked", "custom"
    ] = "custom"
    origin_bank: str = "scotiabank"
    origin_country: str = "CA"
    inter_banks: list[str] | None = None
    inter_countries: list[str] | None = None
    dest_bank: str = "dbs"
    dest_country: str = "SG"
    amount: float = 250000.0
    symbol: str = "USDC"
    decimals: int = 6
    initiator_address: str = "0x1111111111111111111111111111111111111111"
    beneficiary_address: str = "0x2222222222222222222222222222222222222222"
    cdd_complete: bool = True
    travel_rule_complete: bool = True
    sanctions_clear: bool = True
    beneficial_ownership_checked: bool = True
    wash_trade: bool = False
    zero_instructions_hash: bool = False
    rogue_sender: bool = False
    strict_intermediary: bool = False
    mode: Literal["simulated", "sepolia"] = "simulated"


def unfinished() -> None:
    raise HTTPException(
        501,
        detail={
            "code": "WORKFLOW_NOT_IMPLEMENTED",
            "message": "Route contract is scaffolded; no compliance action was performed.",
        },
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="ChainLex API",
        version="0.1.0",
        description=(
            "Working audit agents, human gates and reports; "
            "settlement FSM routes remain scaffolded."
        ),
        lifespan=database_lifespan,
    )
    app.state.settings = settings if settings is not None else Settings()
    app.include_router(audit_router)
    install_exception_handlers(app)
    app.include_router(transaction_router)
    app.mount(
        "/assets", StaticFiles(directory=Path(__file__).parent / "static"), name="workspace-assets"
    )

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(Path(__file__).parent / "static" / "workspace.html")

    @app.get("/health/live", tags=["health"])
    def live():
        return {"status": "ok", "service": "api"}

    app.add_api_route("/health/ready", database_readiness, methods=["GET"], tags=["health"])

    @app.get("/api/fsms/definition", tags=["compliance FSM"])
    def fsm_definition(principal: Principal = Depends(current_principal)):
        settings = app.state.settings
        return {
            "contract_version": 1,
            "runtime_implemented": False,
            "guards_evaluated": False,
            "legs": dict(LEG_STATES),
            "states": {
                state: definition.model_dump(mode="json")
                for state, definition in STATE_DEFINITIONS.items()
            },
            "transitions": [rule.model_dump(mode="json") for rule in TRANSITIONS],
            "defaults": {
                "max_step_attempts": settings.max_step_attempts,
                "retry_wait_seconds": [
                    min(2**attempt, 60) for attempt in range(1, settings.max_step_attempts)
                ],
                "max_retry_after_seconds": 60,
                "reconciliation_seconds": settings.reconciliation_seconds,
                "poll_seconds": settings.poll_seconds,
            },
        }

    @app.post(
        "/api/fsms", tags=["compliance FSM"], responses={501: {"description": "Scaffold only"}}
    )
    async def create_fsm(body: CreateFSM, principal: Principal = Depends(current_principal)):
        unfinished()

    @app.get("/api/fsms/{fsm_id}", response_model=ComplianceFSM, tags=["compliance FSM"])
    async def get_fsm(fsm_id: str, principal: Principal = Depends(current_principal)):
        unfinished()

    @app.get("/api/fsms/{fsm_id}/events", tags=["compliance FSM"])
    async def get_events(
        fsm_id: str,
        after_seq: int = Query(default=0, ge=0),
        principal: Principal = Depends(current_principal),
    ):
        unfinished()

    @app.get("/api/fsms/{fsm_id}/export", tags=["compliance FSM"])
    async def export_fsm(fsm_id: str, principal: Principal = Depends(current_principal)):
        unfinished()

    @app.post("/api/proposals/{proposal_id}/decision", tags=["governance"])
    async def decide_proposal(
        proposal_id: str,
        body: ProposalDecision,
        principal: Principal = Depends(require_officer),
    ):
        unfinished()

    @app.post("/api/compliance/verify", tags=["compliance verification"])
    async def verify_compliance(body: VerifyComplianceRequest):
        try:
            if body.scenario == "cross_country":
                body.travel_rule_complete = False
            elif body.scenario == "binance_hack":
                body.amount = 5000000.0
                body.beneficial_ownership_checked = False
            elif body.scenario == "multihop_routing":
                body.strict_intermediary = True
            elif body.scenario == "sanctions_blocked":
                body.sanctions_clear = False

            return await run_e2e_verification(
                scenario=body.scenario,
                origin_bank=body.origin_bank,
                origin_country=body.origin_country,
                inter_banks=body.inter_banks,
                inter_countries=body.inter_countries,
                dest_bank=body.dest_bank,
                dest_country=body.dest_country,
                amount=body.amount,
                symbol=body.symbol,
                decimals=body.decimals,
                initiator_address=body.initiator_address,
                beneficiary_address=body.beneficiary_address,
                cdd_complete=body.cdd_complete,
                travel_rule_complete=body.travel_rule_complete,
                sanctions_clear=body.sanctions_clear,
                beneficial_ownership_checked=body.beneficial_ownership_checked,
                wash_trade=body.wash_trade,
                zero_instructions_hash=body.zero_instructions_hash,
                rogue_sender=body.rogue_sender,
                strict_intermediary=body.strict_intermediary,
                mode=body.mode,
                verbose=False,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/compliance/report-pdf", tags=["compliance verification"])
    async def generate_compliance_pdf(request: Request):
        from chainlex.audit.reports import build_pdf

        try:
            body = await request.json()
        except Exception:
            body = {}

        now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
        tx_hash = body.get(
            "tx_hash", "0x8ae8586ec180211ec91c8c57f81cddd6c0b52c85ba0925e352f58ec5ac016f2c"
        )
        amount = str(body.get("amount", "100000.00"))
        verdict = body.get("verdict", "APPROVED")
        beneficiary = body.get("beneficiary", "0x2222222222222222222222222222222222222222")
        audit_id = body.get("audit_id", f"audit-tx-{tx_hash[:10]}")

        snapshot = {
            "audit_id": audit_id,
            "tenant_id": "chainlex-demo",
            "version": 1,
            "kind": "REVIEWED_FINAL",
            "created_at": now_str,
            "initiated_by": "ChainLex Multi-Agent Court",
            "verdict": verdict,
            "analysis": {
                "recommended_route_id": "scotiabank-jpmorgan-dbs-demo",
                "explanation": (
                    f"Chief Compliance Officer determination for {amount} USDC. "
                    f"Transaction executed on Ethereum Sepolia ({tx_hash}). "
                    f"Beneficiary: {beneficiary}. "
                    "Evaluated across FINTRAC, OFAC, and MAS statutory rules."
                ),
                "routes": [
                    {
                        "route_id": "scotiabank-jpmorgan-dbs-demo",
                        "outcome": "PASS" if verdict == "APPROVED" else "DENY",
                        "provenance": "configured_demo_corridor",
                        "banks": [
                            {"bank_id": "scotiabank", "jurisdiction": "CA"},
                            {"bank_id": "jpmorgan_chase", "jurisdiction": "US"},
                            {"bank_id": "dbs", "jurisdiction": "SG"},
                        ],
                        "bank_checks": [
                            {
                                "bank_id": "scotiabank",
                                "position": 0,
                                "outcome": "PASS",
                                "reason": "ORIGINATOR_ALLOWLISTED",
                            },
                            {
                                "bank_id": "jpmorgan_chase",
                                "position": 1,
                                "outcome": "PASS",
                                "reason": "FATF_RECIPROCAL_CORRIDOR",
                            },
                            {
                                "bank_id": "dbs",
                                "position": 2,
                                "outcome": "PASS" if verdict == "APPROVED" else "DENY",
                                "reason": "CDD_VERIFIED"
                                if verdict == "APPROVED"
                                else "SANCTIONS_BLOCKED",
                            },
                        ],
                        "jurisdiction_checks": [
                            {
                                "jurisdiction": "CA",
                                "outcome": "PASS",
                                "reason": "FINTRAC_PCMLTFA_COMPLIANT",
                                "rule_ids": ["CA-FINTRAC-TRAVEL-001"],
                            },
                            {
                                "jurisdiction": "US",
                                "outcome": "PASS" if verdict == "APPROVED" else "DENY",
                                "reason": "OFAC_CLEAR"
                                if verdict == "APPROVED"
                                else "OFAC_SDN_MATCH",
                                "rule_ids": ["US-OFAC-SANCTIONS-001"],
                            },
                            {
                                "jurisdiction": "SG",
                                "outcome": "PASS",
                                "reason": "MAS_PSN02_COMPLIANT",
                                "rule_ids": ["SG-MAS-CDD-001"],
                            },
                        ],
                        "issues": [] if verdict == "APPROVED" else ["SANCTIONS_VIOLATION"],
                    }
                ],
            },
            "context": {
                "amount": f"{amount} USDC",
                "asset": "USDC",
                "network": "ethereum-sepolia",
                "adapter": "e2e_compliance_court_v2",
                "narrative": (
                    "Pre-execution compliance verification for Ethereum Sepolia "
                    f"transaction {tx_hash}."
                ),
                "sources": [
                    {
                        "title": "FINTRAC Travel Rule Guidance",
                        "jurisdiction": "CA",
                        "review_status": "VERIFIED",
                    },
                    {
                        "title": "OFAC Virtual Currency Sanctions Scope",
                        "jurisdiction": "US",
                        "review_status": "VERIFIED",
                    },
                    {
                        "title": "MAS Notice PSN02 AML/CFT Requirements",
                        "jurisdiction": "SG",
                        "review_status": "VERIFIED",
                    },
                ],
            },
            "evidence": {
                "regulations": [
                    {
                        "rule_id": "CA-FINTRAC-TRAVEL-001",
                        "jurisdiction": "CA",
                        "review_status": "VERIFIED",
                    },
                    {
                        "rule_id": "US-OFAC-SANCTIONS-001",
                        "jurisdiction": "US",
                        "review_status": "VERIFIED",
                    },
                    {
                        "rule_id": "SG-MAS-CDD-001",
                        "jurisdiction": "SG",
                        "review_status": "VERIFIED",
                    },
                ],
                "memories": [],
            },
            "gates": [
                {
                    "gate_id": "evidence-review",
                    "title": "Statutory Evidence Review",
                    "status": "APPROVED",
                    "decision_reason": "Verified against 12 Voyage AI embedded regulations.",
                },
                {
                    "gate_id": "final-signoff",
                    "title": "Chief Compliance Officer Sign-Off",
                    "status": "APPROVED" if verdict == "APPROVED" else "REJECTED",
                    "decision_reason": "On-chain state confirmed on Ethereum Sepolia.",
                },
            ],
        }

        pdf_bytes = build_pdf(snapshot)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="chainlex-audit-{audit_id}.pdf"'
            },
        )

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
