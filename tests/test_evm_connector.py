"""Unit tests for EVMConnector using mock JSON-RPC responses."""

import httpx
import pytest

from chainlex.connectors.evm import EVMConnector, _to_bytes32
from chainlex.domain.models import HoldAction, ProbeOutcome


def test_to_bytes32_hashing():
    raw_id = "settlement_demo_001"
    b32 = _to_bytes32(raw_id)
    assert b32.startswith("0x")
    assert len(b32) == 66

    # Preserves already formatted 32-byte hex
    already_b32 = "0x" + "aa" * 32
    assert _to_bytes32(already_b32) == already_b32


@pytest.mark.asyncio
async def test_evm_connector_prepare():
    action = HoldAction(
        tenant_id="bank_a",
        settlement_id="tx_test_1001",
        amount_minor=10000000,
    )
    connector = EVMConnector(
        rpc_url="http://localhost:8545",
        contract_address="0x1111111111111111111111111111111111111111",
    )
    prepared = await connector.prepare(action, idempotency_key="idem_001")
    assert prepared.action == action
    assert prepared.idempotency_key == "idem_001"
    assert len(prepared.operation_id) == 64
    assert len(prepared.payload_digest) == 64


@pytest.mark.asyncio
async def test_evm_connector_dispatch_and_probe_confirmed():
    # Mock transport simulating JSON-RPC eth_sendTransaction & eth_call
    def handler(request: httpx.Request) -> httpx.Response:
        import json
        body = json.loads(request.content)
        method = body.get("method")
        if method == "eth_sendTransaction":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0xabc123"})
        elif method == "eth_call":
            # isSettlementHeld returns true (0x000...01)
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "id": 1, "result": "0x0000000000000000000000000000000000000000000000000000000000000001"}
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = EVMConnector(
        rpc_url="http://mock-rpc",
        contract_address="0x1111111111111111111111111111111111111111",
        client=client,
    )

    action = HoldAction(
        tenant_id="bank_a",
        settlement_id="tx_test_1001",
        amount_minor=10000000,
    )
    prepared = await connector.prepare(action, idempotency_key="idem_001")
    dispatch_ref = await connector.dispatch(prepared)

    assert dispatch_ref.provider == "evm"
    assert dispatch_ref.tx_hash == "0xabc123"

    probe_result = await connector.probe(prepared)
    assert probe_result.outcome == ProbeOutcome.CONFIRMED
    assert probe_result.effect == "HELD"
    assert probe_result.settlement_id == "tx_test_1001"

    await connector.close()


@pytest.mark.asyncio
async def test_evm_connector_probe_reverted():
    def handler(request: httpx.Request) -> httpx.Response:
        import json
        body = json.loads(request.content)
        method = body.get("method")
        if method == "eth_sendTransaction":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0xrevert999"})
        elif method == "eth_call":
            # isSettlementHeld returns false
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "id": 1, "result": "0x0000000000000000000000000000000000000000000000000000000000000000"}
            )
        elif method == "eth_getTransactionReceipt":
            # status == 0x0 (reverted)
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"status": "0x0"}})
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = EVMConnector(
        rpc_url="http://mock-rpc",
        contract_address="0x1111111111111111111111111111111111111111",
        client=client,
    )

    action = HoldAction(
        tenant_id="bank_a",
        settlement_id="tx_fail_002",
        amount_minor=50000000,
    )
    prepared = await connector.prepare(action, idempotency_key="idem_002")
    await connector.dispatch(prepared)

    probe_result = await connector.probe(prepared)
    assert probe_result.outcome == ProbeOutcome.REVERTED
    await connector.close()

