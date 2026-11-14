"""Independent, persistent simulator HTTP process."""

import argparse

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pymongo.errors import PyMongoError

from chainlex.auth import require_simulator_token
from chainlex.config import Settings
from chainlex.db.connection import database_lifespan, database_readiness, get_database
from chainlex.domain.models import DispatchReference, PreparedAction, ProbeResult
from chainlex.simulator.store import InvalidPreparedAction, MongoOperationStore, OperationConflict


def create_app(
    settings: Settings | None = None, store: MongoOperationStore | None = None
) -> FastAPI:
    app = FastAPI(title="ChainLex Settlement Simulator", lifespan=database_lifespan)
    app.state.settings = settings if settings is not None else Settings()
    app.state.operation_store = store

    def get_store(request: Request) -> MongoOperationStore:
        if request.app.state.operation_store is not None:
            return request.app.state.operation_store
        database = get_database(request)
        return MongoOperationStore(
            database.simulator_operations,
            request.app.state.settings.simulator_confirmation_seconds,
        )

    @app.get("/health/live", tags=["health"])
    def live():
        return {"status": "ok", "service": "simulator"}

    app.add_api_route("/health/ready", database_readiness, methods=["GET"], tags=["health"])

    @app.post(
        "/operations",
        response_model=DispatchReference,
        dependencies=[Depends(require_simulator_token)],
    )
    async def dispatch(
        prepared: PreparedAction, operations: MongoOperationStore = Depends(get_store)
    ):
        try:
            return await operations.dispatch(prepared)
        except InvalidPreparedAction as exc:
            raise HTTPException(422, str(exc)) from exc
        except OperationConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except PyMongoError as exc:
            raise HTTPException(503, "Simulator database unavailable") from exc

    @app.get(
        "/operations/{operation_id}",
        response_model=ProbeResult,
        dependencies=[Depends(require_simulator_token)],
    )
    async def probe(
        operation_id: str,
        tenant_id: str = Query(min_length=1, max_length=128),
        operations: MongoOperationStore = Depends(get_store),
    ):
        try:
            return await operations.probe(operation_id, tenant_id)
        except PyMongoError as exc:
            raise HTTPException(503, "Simulator database unavailable") from exc

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    uvicorn.run(create_app(), host=args.host, port=args.port)
