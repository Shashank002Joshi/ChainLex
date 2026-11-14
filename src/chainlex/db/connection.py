"""Async client lifecycle and sanitized readiness errors."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from chainlex.config import Settings


def create_client(settings: Settings) -> AsyncMongoClient:
    if settings.mongodb_uri is None or not settings.mongodb_uri.get_secret_value():
        raise ValueError("CHAINLEX_MONGODB_URI is required")
    return AsyncMongoClient(
        settings.mongodb_uri.get_secret_value(),
        serverSelectionTimeoutMS=settings.database_timeout_ms,
        connectTimeoutMS=settings.database_timeout_ms,
        tz_aware=True,
        appname="chainlex",
    )


@asynccontextmanager
async def database_lifespan(app: FastAPI):
    settings = app.state.settings
    client = create_client(settings) if settings.mongodb_uri else None
    app.state.mongo_client = client
    app.state.database = client[settings.database] if client is not None else None
    try:
        yield
    finally:
        if client is not None:
            await client.close()


def get_database(request: Request):
    database = request.app.state.database
    if database is None:
        raise HTTPException(503, detail={"code": "DATABASE_NOT_CONFIGURED"})
    return database


async def database_readiness(request: Request):
    database = get_database(request)
    try:
        await database.command("ping")
    except PyMongoError as exc:
        raise HTTPException(503, detail={"code": "DATABASE_UNAVAILABLE"}) from exc
    return {"status": "ready", "database": "reachable", "workflow": "audit_agents"}
