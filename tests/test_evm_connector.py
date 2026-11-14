"""Unit tests for EVMConnector validating calldata, durable dispatch, and confirmations."""

import httpx
import pytest

from chainlex.blockchain.artifacts import TOPIC_SETTLEMENT_FROZEN
from chainlex.connectors.evm import EVMConnector, _to_bytes32
from chainlex.domain.models import HoldAction, ProbeOutcome


class FakeOutboxCollection:
    def __init__(self):
        self.docs = {}

    async def update_one(self, query, update, upsert=False):
        key = (query.get("tenant_id"), query.get("operation_id"))
        if key not in self.docs and upsert:
            self.docs[key] = query.copy()
        if key in self.docs and "$set" in update:
            self.docs[key].update(update["$set"])

    async def find_one(self, query):
        key = (query.get("tenant_id"), query.get("operation_id"))
        return self.docs.get(key)


def test_to_bytes32_hashing():
    raw_id = "settlement_demo_001"
    b32 = _to_bytes32(raw_id)
    assert b32.startswith("0x")
    assert len(b32) == 66

    already_b32 = "0x" + "aa" * 32
    assert _to_bytes32(already_b32) == already_b32.lower()


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


@pytest.mark.asyncio
async def test_evm_connector_calldata_and_rejection_propagation():
    def rejecting_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32000, "message": "insufficient funds"},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(rejecting_handler))
    connector = EVMConnector(
        rpc_url="http://mock-rpc",
        contract_address="0x1111111111111111111111111111111111111111",
        client=client,
    )

    action = HoldAction(tenant_id="bank_a", settlement_id="tx_test_1001", amount_minor=10000000)
    prepared = await connector.prepare(action, idempotency_key="idem_001")

    # Errors must propagate directly and never manufacture fake hashes
    with pytest.raises(RuntimeError, match="insufficient funds"):
        await connector.dispatch(prepared)

    await connector.close()


@pytest.mark.asyncio
async def test_evm_connector_durable_restart_and_verification_rules():
    outbox = FakeOutboxCollection()
    settlement_b32 = _to_bytes32("tx_test_1001")

    current_block_num = 105

    def rpc_handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        method = body.get("method")
        params = body.get("params", [])

        if method == "eth_sendTransaction":
            calldata = params[0].get("data", "")
            # Must contain selector 1dd281a8 and settlement id
            assert calldata.startswith("0x1dd281a8")
            assert settlement_b32[2:] in calldata
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "id": 1, "result": "0xreal_tx_hash_123"}
            )
        elif method == "eth_blockNumber":
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "id": 1, "result": hex(current_block_num)}
            )
        elif method == "eth_getTransactionReceipt":
            # Valid receipt at block 100 with expected SettlementFrozen event log
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "status": "0x1",
                        "blockNumber": "0x64",  # block 100
                        "logs": [
                            {
                                "topics": [TOPIC_SETTLEMENT_FROZEN, settlement_b32],
                                "data": "0x",
                            }
                        ],
                    },
                },
            )
        elif method == "eth_call":
            # isSettlementHeld view returns true
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": "0x0000000000000000000000000000000000000000000000000000000000000001",
                },
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(rpc_handler))
    connector1 = EVMConnector(
        rpc_url="http://mock-rpc",
        contract_address="0x1111111111111111111111111111111111111111",
        client=client,
        outbox_collection=outbox,
        required_confirmations=3,
    )

    action = HoldAction(tenant_id="bank_a", settlement_id="tx_test_1001", amount_minor=10000000)
    prepared = await connector1.prepare(action, idempotency_key="idem_001")
    ref = await connector1.dispatch(prepared)
    assert ref.tx_hash == "0xreal_tx_hash_123"

    # Simulate worker restart: create connector2 with identical durable outbox
    connector2 = EVMConnector(
        rpc_url="http://mock-rpc",
        contract_address="0x1111111111111111111111111111111111111111",
        client=client,
        outbox_collection=outbox,
        required_confirmations=3,
    )

    # 1. Probing with 105 - 100 + 1 = 6 confirmations (>= 3) -> CONFIRMED
    res = await connector2.probe(prepared)
    assert res.outcome == ProbeOutcome.CONFIRMED
    assert res.effect == "HELD"

    # 2. Test insufficient confirmations
    current_block_num = 101  # 101 - 100 + 1 = 2 (< 3)
    res_pending = await connector2.probe(prepared)
    assert res_pending.outcome == ProbeOutcome.PENDING

    await connector1.close()
    await connector2.close()
