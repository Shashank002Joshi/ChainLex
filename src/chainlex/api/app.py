"""API process: runnable health checks and validated workflow route contracts."""

import argparse
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
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

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(create_app(), host=args.host, port=args.port)
