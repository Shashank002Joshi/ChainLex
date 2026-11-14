"""Demo identities are bound to tenant/role on the server, not in request bodies."""

import secrets
from typing import Literal

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict

bearer = HTTPBearer(auto_error=False)


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True)
    tenant_id: str
    role: Literal["analyst", "officer"]


def current_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Principal:
    if credentials is None:
        raise HTTPException(401, "Bearer token required", headers={"WWW-Authenticate": "Bearer"})
    settings = request.app.state.settings
    for role, token in (("analyst", settings.analyst_token), ("officer", settings.officer_token)):
        expected = token.get_secret_value()
        if expected and secrets.compare_digest(credentials.credentials.encode(), expected.encode()):
            return Principal(tenant_id=settings.demo_tenant_id, role=role)
    raise HTTPException(401, "Invalid token", headers={"WWW-Authenticate": "Bearer"})


def require_officer(principal: Principal = Depends(current_principal)) -> Principal:
    if principal.role != "officer":
        raise HTTPException(403, "Officer role required")
    return principal


def require_simulator_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> None:
    expected = request.app.state.settings.simulator_token.get_secret_value()
    if not expected:
        raise HTTPException(503, "Simulator token is not configured")
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(), expected.encode()
    ):
        raise HTTPException(401, "Invalid simulator token", headers={"WWW-Authenticate": "Bearer"})
