"""Transaction boundaries and receipt verification; never broadcasts to Sepolia."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from eth_abi import decode
from eth_account import Account
from fastapi import HTTPException
from pydantic import SecretStr, ValidationError

from chainlex.api.transactions import (
    CHAIN_ID,
    CreateTransaction,
    TransactionService,
    configuration,
    encode_request,
    public_transaction,
    service,
)
from chainlex.blockchain.artifacts import TOPIC_SETTLEMENT_INITIATED_V2
from chainlex.config import Settings


def request(**changes):
    return CreateTransaction.model_validate(
        {
            "amount": "250000.000001",
            "beneficiary": "0x" + "22" * 20,
            "asset_contract": "0x" + "33" * 20,
            "route_id": "scotiabank-jpmorgan-dbs-demo",
            "idempotency_key": "request-1",
            **changes,
        }
    )


def record(**changes):
    return {
        "_id": "bank_a:request-1",
        "tenant_id": "bank_a",
        "transaction_id": "txn-1",
        "state": "SUBMITTED",
        "tx_hash": "0x" + "ab" * 32,
        "contract_address": "0x" + "44" * 20,
        "settlement_id": "0x" + "cd" * 32,
        "signed_raw_tx": "private-signed-bytes",
        **changes,
    }


def test_calldata_preserves_exact_amount_and_every_corridor_leg():
    payload = bytes.fromhex(encode_request(request(), "0x" + "cd" * 32)[2:])
    identity, beneficiary, details = decode(
        ["bytes32", "address", "(uint256,string,uint8,address,string,string[],string[],bytes32)"],
        payload[4:],
    )
    assert identity == bytes.fromhex("cd" * 32)
    assert beneficiary == "0x" + "22" * 20
    assert details[0] == 250000000001
    assert details[1:3] == ("USDC", 6)
    assert details[5] == ("scotiabank", "jpmorgan_chase", "dbs")
    assert details[6] == ("CA", "US", "SG")


@pytest.mark.parametrize(
    "changes",
    [
        {"amount": "0"},
        {"amount": "-1"},
        {"amount": "1.0000001"},
        {"amount": "1e6"},
        {"beneficiary": "0x" + "00" * 20},
        {"asset_contract": "bad"},
        {"route_id": "arbitrary-contract-call"},
        {"tenant_id": "other-tenant"},
        {"private_key": "not-a-browser-field"},
        {"chain_id": 1},
    ],
)
def test_request_rejects_invalid_or_caller_controlled_authority(changes):
    with pytest.raises(ValidationError):
        request(**changes)


def test_configuration_and_api_output_never_expose_signing_material():
    account = Account.create()
    settings = Settings(
        _env_file=None,
        sepolia_private_key=SecretStr(account.key.hex()),
        sepolia_contract_address="0x" + "44" * 20,
    )
    config = configuration(settings)
    assert config["configured"] is True
    assert config["signer"] == account.address
    assert account.key.hex() not in str(config)
    result = public_transaction(record(private_key="secret", nonce=5))
    assert "signed_raw_tx" not in result
    assert "private_key" not in result
    assert "nonce" not in result


@pytest.mark.parametrize(
    "receipt_status,include_event,expected",
    [
        ("0x1", True, "CONFIRMED"),
        ("0x1", False, "RECEIPT_REQUIRES_REVIEW"),
        ("0x0", False, "REVERTED"),
    ],
)
async def test_confirmation_requires_matching_receipt_and_expected_event(
    receipt_status, include_event, expected
):
    saved = record()
    db = SimpleNamespace(sepolia_transactions=SimpleNamespace(update_one=AsyncMock()))
    engine = TransactionService(db, Settings(_env_file=None))
    engine.get = AsyncMock(return_value=saved)
    receipt = {
        "transactionHash": saved["tx_hash"],
        "status": receipt_status,
        "blockNumber": "0x123",
        "logs": [
            {
                "address": saved["contract_address"],
                "topics": [TOPIC_SETTLEMENT_INITIATED_V2, saved["settlement_id"]],
            }
        ]
        if include_event
        else [],
    }
    engine.rpc = AsyncMock(side_effect=[hex(CHAIN_ID), receipt])
    result = await engine.probe("bank_a", "txn-1")
    assert result["state"] == expected
    assert result["block_number"] == 0x123
    engine.get.assert_awaited_once_with("bank_a", "txn-1")


async def test_sent_without_receipt_is_not_confirmed():
    db = SimpleNamespace(sepolia_transactions=SimpleNamespace(update_one=AsyncMock()))
    engine = TransactionService(db, Settings(_env_file=None))
    engine.get = AsyncMock(return_value=record())
    engine.rpc = AsyncMock(side_effect=[hex(CHAIN_ID), None])
    assert (await engine.probe("bank_a", "txn-1"))["state"] == "SUBMITTED"
    db.sepolia_transactions.update_one.assert_not_awaited()


async def test_wrong_chain_is_rejected_before_reading_a_receipt():
    engine = TransactionService(None, Settings(_env_file=None))
    engine.get = AsyncMock(return_value=record())
    engine.rpc = AsyncMock(return_value="0x1")
    with pytest.raises(HTTPException) as caught:
        await engine.probe("bank_a", "txn-1")
    assert caught.value.status_code == 503
    engine.rpc.assert_awaited_once_with("eth_chainId", [])


async def test_timeout_preserves_unknown_outcome_and_same_signed_identity():
    db = SimpleNamespace(sepolia_transactions=SimpleNamespace(update_one=AsyncMock()))
    engine = TransactionService(db, Settings(_env_file=None))
    engine.get = AsyncMock(return_value=record(state="SUBMISSION_UNKNOWN"))
    engine.rpc = AsyncMock(side_effect=HTTPException(502, "Timeout"))
    result = await engine.broadcast(record(state="PREPARED"))
    assert result["state"] == "SUBMISSION_UNKNOWN"
    engine.rpc.assert_awaited_once_with("eth_sendRawTransaction", ["private-signed-bytes"])
    assert db.sepolia_transactions.update_one.await_args.args[1]["$set"]["state"] == (
        "SUBMISSION_UNKNOWN"
    )
    assert (
        db.sepolia_transactions.update_one.await_args.args[1]["$set"]["submission_error"]
        == "Timeout"
    )


async def test_rpc_rejection_preserves_specific_reason_without_returning_signed_material():
    def respond(request):
        return httpx.Response(
            200, json={"error": {"code": -32000, "message": "insufficient funds for gas"}}
        )

    engine = TransactionService(
        None, Settings(_env_file=None), transport=httpx.MockTransport(respond)
    )
    with pytest.raises(HTTPException) as caught:
        await engine.rpc("eth_estimateGas", [])
    assert caught.value.status_code == 502
    assert (
        caught.value.detail
        == "Sepolia eth_estimateGas rejected the request: insufficient funds for gas"
    )


def test_transaction_mutations_require_officer_and_derive_tenant(client):
    fake = SimpleNamespace(
        submit=AsyncMock(return_value=record()), probe=AsyncMock(return_value=record())
    )
    client.app.dependency_overrides[service] = lambda: fake
    try:
        assert client.post("/api/transactions", json=request().model_dump()).status_code == 401
        analyst = {"Authorization": "Bearer analyst-test-token"}
        officer = {"Authorization": "Bearer officer-test-token"}
        assert (
            client.post(
                "/api/transactions", headers=analyst, json=request().model_dump()
            ).status_code
            == 403
        )
        response = client.post("/api/transactions", headers=officer, json=request().model_dump())
        assert response.status_code == 202
        assert "signed_raw_tx" not in response.json()
        assert fake.submit.await_args.args[:2] == ("bank_a", "bank_a:officer")
        assert client.get("/api/transactions/config", headers=analyst).json()["configured"] is False
    finally:
        client.app.dependency_overrides.pop(service)
