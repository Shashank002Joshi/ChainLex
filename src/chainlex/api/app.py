"""API process: runnable health checks and validated workflow route contracts."""

import argparse
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from chainlex.auth import Principal, current_principal, require_officer
from chainlex.config import Settings
from chainlex.db.connection import database_lifespan, database_readiness
from chainlex.domain.models import ControlRequest, CreateJob, InvalidateMemory, ProposalDecision


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
        description="Scaffold contracts; workflow operations currently return 501.",
        lifespan=database_lifespan,
    )
    app.state.settings = settings if settings is not None else Settings()

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.get("/health/live", tags=["health"])
    def live():
        return {"status": "ok", "service": "api"}

    app.add_api_route("/health/ready", database_readiness, methods=["GET"], tags=["health"])

    @app.post("/api/jobs", tags=["jobs"], responses={501: {"description": "Scaffold only"}})
    async def create_job(body: CreateJob, principal: Principal = Depends(current_principal)):
        unfinished()

    @app.get("/api/jobs/{job_id}", tags=["jobs"])
    async def get_job(job_id: str, principal: Principal = Depends(current_principal)):
        unfinished()

    @app.get("/api/jobs/{job_id}/events", tags=["jobs"])
    async def get_events(
        job_id: str,
        after_seq: int = Query(default=0, ge=0),
        principal: Principal = Depends(current_principal),
    ):
        unfinished()

    @app.get("/api/jobs/{job_id}/export", tags=["jobs"])
    async def export_job(job_id: str, principal: Principal = Depends(current_principal)):
        unfinished()

    @app.post("/api/proposals/{proposal_id}/decision", tags=["governance"])
    async def decide_proposal(
        proposal_id: str,
        body: ProposalDecision,
        principal: Principal = Depends(require_officer),
    ):
        unfinished()

    @app.post("/api/control", tags=["governance"])
    async def control(body: ControlRequest, principal: Principal = Depends(require_officer)):
        unfinished()

    @app.post("/api/memories/{memory_id}/invalidate", tags=["governance"])
    async def invalidate_memory(
        memory_id: str,
        body: InvalidateMemory,
        principal: Principal = Depends(require_officer),
    ):
        unfinished()

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(create_app(), host=args.host, port=args.port)
