"""HTTP adapter; caller owns the HTTPX client lifecycle and retry policy."""

import hashlib
import json

import httpx

from chainlex.domain.models import DispatchReference, HoldAction, PreparedAction, ProbeResult


def prepare_action(action: HoldAction, idempotency_key: str) -> PreparedAction:
    payload = json.dumps(action.model_dump(), sort_keys=True, separators=(",", ":"))
    identity = json.dumps([action.tenant_id, idempotency_key], separators=(",", ":"))
    return PreparedAction(
        action=action,
        idempotency_key=idempotency_key,
        operation_id=hashlib.sha256(identity.encode()).hexdigest(),
        payload_digest=hashlib.sha256(payload.encode()).hexdigest(),
    )


class SimulatorConnector:
    def __init__(self, client: httpx.AsyncClient, token: str):
        self.client = client
        self.headers = {"Authorization": f"Bearer {token}"}

    async def prepare(self, action: HoldAction, idempotency_key: str) -> PreparedAction:
        return prepare_action(action, idempotency_key)

    async def dispatch(self, prepared_action: PreparedAction) -> DispatchReference:
        response = await self.client.post(
            "/operations", json=prepared_action.model_dump(mode="json"), headers=self.headers
        )
        response.raise_for_status()
        return DispatchReference.model_validate(response.json())

    async def probe(self, prepared_action: PreparedAction) -> ProbeResult:
        response = await self.client.get(
            f"/operations/{prepared_action.operation_id}",
            params={"tenant_id": prepared_action.action.tenant_id},
            headers=self.headers,
        )
        response.raise_for_status()
        return ProbeResult.model_validate(response.json())
