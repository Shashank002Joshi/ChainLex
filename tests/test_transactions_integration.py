"""Real disposable Atlas persistence with a mocked Sepolia RPC; never spends gas."""

import json
import os
from uuid import uuid4

import httpx
import pytest
from eth_account import Account
from fastapi import HTTPException
from pydantic import SecretStr
from pymongo import AsyncMongoClient

from chainlex.api.transaction_audit import link_audit
from chainlex.api.transactions import CHAIN_ID, CreateTransaction, TransactionService
from chainlex.audit.repository import AuditRepository, verify_ledger
from chainlex.auth import Principal
from chainlex.blockchain.artifacts import TOPIC_SETTLEMENT_INITIATED_V2
from chainlex.config import Settings
from chainlex.db.indexes import bootstrap

pytestmark = pytest.mark.integration


async def test_durable_signed_submission_receipt_and_linked_audit():
    uri = os.environ.get("CHAINLEX_TEST_MONGODB_URI")
    if not uri:
        pytest.skip("Requires a disposable Atlas/replica-set test database")
    client = AsyncMongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=5000)
    name = "chainlex_test_ui_" + uuid4().hex
    db = client[name]
    account = Account.create()
    settings = Settings(
        _env_file=None,
        sepolia_private_key=SecretStr(account.key.hex()),
        sepolia_contract_address="0x" + "44" * 20,
    )
    sent = []

    async def rpc(request):
        data = json.loads(request.content)
        method, params = data["method"], data["params"]
        if method == "eth_chainId":
            result = hex(CHAIN_ID)
        elif method == "eth_getTransactionCount":
            result = "0x0"
        elif method == "eth_estimateGas":
            result = "0x30000"
        elif method == "eth_gasPrice":
            result = "0x3b9aca00"
        elif method == "eth_sendRawTransaction":
            # This assertion runs at the external-send boundary, after the transaction commit.
            saved = await db.sepolia_transactions.find_one({"signed_raw_tx": params[0]})
            assert saved is not None
            assert saved["state"] in {"PREPARED", "SUBMISSION_UNKNOWN"}
            assert Account.recover_transaction(params[0]) == account.address
            sent.append(params[0])
            result = saved["tx_hash"]
        elif method == "eth_getTransactionReceipt":
            saved = await db.sepolia_transactions.find_one({"tx_hash": params[0]})
            result = {
                "transactionHash": saved["tx_hash"],
                "status": "0x1",
                "blockNumber": "0x123",
                "logs": [
                    {
                        "address": settings.sepolia_contract_address,
                        "topics": [TOPIC_SETTLEMENT_INITIATED_V2, saved["settlement_id"]],
                    }
                ],
            }
        else:
            pytest.fail(f"Unexpected RPC method {method}")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    try:
        await bootstrap(db)
        engine = TransactionService(db, settings, transport=httpx.MockTransport(rpc))
        body = CreateTransaction(
            amount="250000.000001",
            beneficiary="0x" + "22" * 20,
            asset_contract="0x" + "33" * 20,
            route_id="scotiabank-jpmorgan-dbs-demo",
            idempotency_key="upstream-request-1",
        )
        first = await engine.submit("bank_a", "bank_a:officer", body)
        assert first["state"] == "SUBMITTED"
        assert len(first["tx_hash"]) == 66
        again = await engine.submit("bank_a", "bank_a:officer", body)
        assert first["transaction_id"] == again["transaction_id"]
        assert len(sent) == 1
        with pytest.raises(HTTPException) as conflict:
            await engine.submit("bank_a", "bank_a:officer", body.model_copy(update={"amount": "1"}))
        assert conflict.value.status_code == 409
        with pytest.raises(HTTPException) as wrong_tenant:
            await engine.get("bank_b", first["transaction_id"])
        assert wrong_tenant.value.status_code == 404
        confirmed = await engine.probe("bank_a", first["transaction_id"])
        assert confirmed["state"] == "CONFIRMED"
        linked = await link_audit(db, Principal(tenant_id="bank_a", role="officer"), confirmed)
        repeated = await link_audit(db, Principal(tenant_id="bank_a", role="officer"), confirmed)
        assert linked == repeated
        repo = AuditRepository(db)
        run = await repo.get("bank_a", linked["audit_id"])
        assert run.checkpoint["source"]["amount"] == "250000.000001"
        assert run.checkpoint["source"]["routes"][0]["route_id"] == body.route_id
        assert run.checkpoint["source"]["transaction_reference"]["tx_hash"] == first["tx_hash"]
        events = await repo.events("bank_a", run.audit_id)
        assert verify_ledger(events, expected_last_hash=run.last_event_hash)
        assert await db.compliance_fsms.count_documents({"fsm_id": run.audit_id}) == 1
        second = await engine.submit(
            "bank_a",
            "bank_a:officer",
            body.model_copy(update={"idempotency_key": "upstream-request-2"}),
        )
        assert second["nonce"] == first["nonce"] + 1
        await db.tenant_controls.update_one({"tenant_id": "bank_a"}, {"$set": {"paused": True}})
        with pytest.raises(HTTPException) as paused:
            await engine.submit(
                "bank_a",
                "bank_a:officer",
                body.model_copy(update={"idempotency_key": "upstream-request-3"}),
            )
        assert paused.value.status_code == 409
        assert len(sent) == 2
    finally:
        await client.drop_database(name)
        await client.close()
