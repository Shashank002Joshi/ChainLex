"""Connector contract shared by the simulator and future EVM adapter."""

from typing import Protocol

from chainlex.domain.models import DispatchReference, HoldAction, PreparedAction, ProbeResult


class SettlementConnector(Protocol):
    async def prepare(self, action: HoldAction, idempotency_key: str) -> PreparedAction: ...

    async def dispatch(self, prepared_action: PreparedAction) -> DispatchReference: ...

    async def probe(self, prepared_action: PreparedAction) -> ProbeResult: ...
