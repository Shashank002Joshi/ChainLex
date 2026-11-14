"""Backend-signed Sepolia requests. Signing material is never returned to clients."""

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import uuid4

import httpx
from eth_abi import encode
from eth_account import Account
from eth_utils import keccak
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, field_validator
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from chainlex.auth import Principal, current_principal, require_officer
from chainlex.blockchain.artifacts import TOPIC_SETTLEMENT_INITIATED_V2
from chainlex.db.connection import get_database
from chainlex.domain.models import Contract, Identifier

router = APIRouter(prefix="/api/transactions", tags=["Sepolia transactions"])
CHAIN_ID = 11155111
ROUTES = {
    "scotiabank-jpmorgan-dbs-demo": (("scotiabank", "CA"), ("jpmorgan_chase", "US"), ("dbs", "SG")),
    "dbs-jpmorgan-scotiabank-demo": (("dbs", "SG"), ("jpmorgan_chase", "US"), ("scotiabank", "CA")),
}


class CreateTransaction(Contract):
    amount: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,20})(?:\.[0-9]{1,6})?$")
    beneficiary: str = Field(pattern=r"^0x[0-9a-fA-F]{40}$")
    asset_contract: str = Field(pattern=r"^0x[0-9a-fA-F]{40}$")
    route_id: Literal["scotiabank-jpmorgan-dbs-demo", "dbs-jpmorgan-scotiabank-demo"]
    idempotency_key: Identifier

    @field_validator("amount")
    @classmethod
    def positive(cls, value):
        if Decimal(value) <= 0:
            raise ValueError("Amount must be positive")
        return value

    @field_validator("beneficiary", "asset_contract")
    @classmethod
    def address(cls, value):
        if int(value, 16) == 0:
            raise ValueError("A nonzero address is required")
        return value.lower()


def configuration(settings):
    signer = None
    key = settings.sepolia_private_key.get_secret_value()
    if key:
        try:
            signer = Account.from_key(key).address
        except (ValueError, TypeError):
            pass
    return {
        "configured": bool(
            signer and settings.sepolia_contract_address and settings.sepolia_rpc_url
        ),
        "chain_id": CHAIN_ID,
        "network": "ethereum-sepolia",
        "signer": signer,
        "contract_address": settings.sepolia_contract_address,
        "routes": list(ROUTES),
    }


def public_transaction(record):
    allowed = {
        "transaction_id",
        "settlement_id",
        "state",
        "tx_hash",
        "submission_error",
        "amount",
        "beneficiary",
        "asset_contract",
        "route_id",
        "chain_id",
        "created_at",
        "updated_at",
        "block_number",
        "audit_id",
        "signer",
        "contract_address",
    }
    return {key: value for key, value in record.items() if key in allowed}


def encode_request(body, settlement_id):
    corridor = ROUTES[body.route_id]
    details = (
        int(Decimal(body.amount) * 10**6),
        "USDC",
        6,
        body.asset_contract,
        body.route_id,
        [b for b, _ in corridor],
        [c for _, c in corridor],
        hashlib.sha256(body.model_dump_json().encode()).digest(),
    )
    signature = (
        "initiateRoutedSettlement(bytes32,address,"
        "(uint256,string,uint8,address,string,string[],string[],bytes32))"
    )
    return (
        "0x"
        + (
            keccak(text=signature)[:4]
            + encode(
                [
                    "bytes32",
                    "address",
                    "(uint256,string,uint8,address,string,string[],string[],bytes32)",
                ],
                [bytes.fromhex(settlement_id[2:]), body.beneficiary, details],
            )
        ).hex()
    )


class TransactionService:
    def __init__(self, database, settings, *, transport=None):
        self.db, self.settings, self.transport = database, settings, transport

    async def rpc(self, method, params):
        try:
            async with httpx.AsyncClient(timeout=12, transport=self.transport) as client:
                response = await client.post(
                    self.settings.sepolia_rpc_url,
                    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                )
                response.raise_for_status()
                data = response.json()
            if data.get("error"):
                error = data["error"]
                message = str(error.get("message", "RPC rejected request"))[:300]
                raise HTTPException(502, f"Sepolia {method} rejected the request: {message}")
            if "result" not in data:
                raise ValueError("RPC rejected request")
            return data["result"]
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise HTTPException(
                502,
                "Sepolia could not complete this request. "
                "Check the backend RPC, signer balance, and contract configuration.",
            ) from exc

    async def require_chain(self):
        if int(await self.rpc("eth_chainId", []), 16) != CHAIN_ID:
            raise HTTPException(503, "The transaction service must use Ethereum Sepolia.")

    async def get(self, tenant, identity):
        record = await self.db.sepolia_transactions.find_one(
            {"tenant_id": tenant, "transaction_id": identity}
        )
        if record is None:
            raise HTTPException(404, "Transaction not found")
        return record

    async def submit(self, tenant, actor, body):
        config = configuration(self.settings)
        if not config["configured"]:
            raise HTTPException(503, "The backend Sepolia signer is not configured.")
        key = f"{tenant}:{body.idempotency_key}"
        input_digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
        existing = await self.db.sepolia_transactions.find_one({"_id": key})
        if existing:
            if existing["input_digest"] != input_digest:
                raise HTTPException(409, "This request key is bound to different inputs.")
            return (
                await self.broadcast(existing)
                if existing["state"] in {"PREPARED", "SUBMISSION_UNKNOWN"}
                else existing
            )
        control = await self.db.tenant_controls.find_one({"tenant_id": tenant})
        if control and control.get("paused"):
            raise HTTPException(409, "This tenant is paused.")
        await self.require_chain()
        signer = config["signer"]
        if body.beneficiary == signer.lower():
            raise HTTPException(422, "Beneficiary must differ from the backend signer.")
        owner, now = uuid4().hex, datetime.now(UTC)
        lock_id = f"sepolia:{signer.lower()}"
        try:
            await self.db.sepolia_signer_locks.find_one_and_update(
                {
                    "_id": lock_id,
                    "$or": [{"expires_at": {"$lte": now}}, {"expires_at": {"$exists": False}}],
                },
                {
                    "$set": {
                        "owner": owner,
                        "expires_at": now + timedelta(seconds=90),
                        "tenant_id": tenant,
                        "schema_version": 1,
                    }
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError as exc:
            raise HTTPException(
                409, "The signer is preparing another transaction. Retry shortly."
            ) from exc
        try:
            nonce = int(await self.rpc("eth_getTransactionCount", [signer, "pending"]), 16)
            last = await self.db.sepolia_transactions.find_one(
                {"signer": signer, "chain_id": CHAIN_ID}, sort=[("nonce", -1)]
            )
            if last:
                nonce = max(nonce, last["nonce"] + 1)
            settlement_id = "0x" + uuid4().hex + uuid4().hex
            data = encode_request(body, settlement_id)
            estimate = int(
                await self.rpc(
                    "eth_estimateGas",
                    [{"from": signer, "to": config["contract_address"], "data": data}],
                ),
                16,
            )
            if estimate > 700000:
                raise HTTPException(422, "Request exceeds the demo transaction gas limit.")
            gas_price = int(await self.rpc("eth_gasPrice", []), 16)
            signed = Account.sign_transaction(
                {
                    "chainId": CHAIN_ID,
                    "nonce": nonce,
                    "to": config["contract_address"],
                    "value": 0,
                    "gas": min(700000, estimate * 12 // 10),
                    "gasPrice": gas_price,
                    "data": data,
                },
                self.settings.sepolia_private_key.get_secret_value(),
            )
            record = {
                "_id": key,
                "tenant_id": tenant,
                "schema_version": 1,
                "transaction_id": "txn-" + uuid4().hex,
                "settlement_id": settlement_id,
                **body.model_dump(),
                "input_digest": input_digest,
                "chain_id": CHAIN_ID,
                "signer": signer,
                "contract_address": config["contract_address"],
                "nonce": nonce,
                "signed_raw_tx": "0x" + signed.raw_transaction.hex(),
                "tx_hash": "0x" + signed.hash.hex(),
                "state": "PREPARED",
                "initiated_by": actor,
                "created_at": now,
                "updated_at": now,
            }

            async def persist(session):
                valid = await self.db.sepolia_signer_locks.find_one(
                    {"_id": lock_id, "owner": owner, "expires_at": {"$gt": datetime.now(UTC)}},
                    session=session,
                )
                if not valid:
                    raise HTTPException(409, "Signer preparation expired. Retry the same request.")
                current = await self.db.tenant_controls.find_one(
                    {"tenant_id": tenant}, session=session
                )
                if current:
                    if current.get("paused"):
                        raise HTTPException(
                            409, "Tenant was paused before submission was permitted."
                        )
                    await self.db.tenant_controls.update_one(
                        {"_id": current["_id"]},
                        {"$inc": {"transaction_permit_serial": 1}},
                        session=session,
                    )
                await self.db.sepolia_transactions.insert_one(dict(record), session=session)
                await self.db.transaction_events.insert_one(
                    {
                        "tenant_id": tenant,
                        "schema_version": 1,
                        "transaction_id": record["transaction_id"],
                        "event_type": "SUBMISSION_PERMITTED",
                        "actor_id": actor,
                        "occurred_at": now,
                        "input_digest": input_digest,
                        "tx_hash": record["tx_hash"],
                    },
                    session=session,
                )
                await self.db.sepolia_signer_locks.update_one(
                    {"_id": lock_id, "owner": owner},
                    {"$unset": {"owner": "", "expires_at": ""}},
                    session=session,
                )

            async with self.db.client.start_session() as session:
                await session.with_transaction(persist)
        except DuplicateKeyError:
            existing = await self.db.sepolia_transactions.find_one({"_id": key})
            if not existing or existing["input_digest"] != input_digest:
                raise HTTPException(
                    409, "Transaction inputs conflict with an existing request."
                ) from None
            record = existing
        finally:
            await self.db.sepolia_signer_locks.update_one(
                {"_id": lock_id, "owner": owner}, {"$unset": {"owner": "", "expires_at": ""}}
            )
        return await self.broadcast(record)

    async def broadcast(self, record):
        submission_error = None
        try:
            result = await self.rpc("eth_sendRawTransaction", [record["signed_raw_tx"]])
            new_state = (
                "SUBMITTED"
                if str(result).lower() == record["tx_hash"].lower()
                else "SUBMISSION_UNKNOWN"
            )
            if new_state == "SUBMISSION_UNKNOWN":
                submission_error = "RPC returned an unexpected hash; broadcast is not confirmed."
        except HTTPException as exc:
            new_state = "SUBMISSION_UNKNOWN"
            submission_error = str(exc.detail)
        await self.db.sepolia_transactions.update_one(
            {"_id": record["_id"], "state": {"$in": ["PREPARED", "SUBMISSION_UNKNOWN"]}},
            {
                "$set": {
                    "state": new_state,
                    "submission_error": submission_error,
                    "updated_at": datetime.now(UTC),
                }
            },
        )
        return await self.get(record["tenant_id"], record["transaction_id"])

    async def probe(self, tenant, identity):
        record = await self.get(tenant, identity)
        if record["state"] in {"CONFIRMED", "REVERTED"}:
            return record
        await self.require_chain()
        receipt = await self.rpc("eth_getTransactionReceipt", [record["tx_hash"]])
        if receipt is None:
            return record
        if str(receipt.get("transactionHash", "")).lower() != record["tx_hash"].lower():
            raise HTTPException(502, "Receipt did not match the saved transaction.")
        success = int(receipt["status"], 16) == 1
        matches = any(
            str(log.get("address", "")).lower() == record["contract_address"].lower()
            and len(log.get("topics", [])) >= 2
            and log["topics"][0].lower() == TOPIC_SETTLEMENT_INITIATED_V2.lower()
            and log["topics"][1].lower() == record["settlement_id"].lower()
            for log in receipt.get("logs", [])
        )
        updates = {
            "state": "CONFIRMED"
            if success and matches
            else "RECEIPT_REQUIRES_REVIEW"
            if success
            else "REVERTED",
            "block_number": int(receipt["blockNumber"], 16),
            "submission_error": None
            if success and matches
            else (
                "The transaction succeeded, but its receipt has no matching settlement event."
                if success
                else "The transaction reverted on-chain."
            ),
            "updated_at": datetime.now(UTC),
        }
        await self.db.sepolia_transactions.update_one({"_id": record["_id"]}, {"$set": updates})
        return {**record, **updates}


def service(request: Request):
    return TransactionService(get_database(request), request.app.state.settings)


@router.get("/config")
def transaction_config(request: Request, principal: Principal = Depends(current_principal)):
    return configuration(request.app.state.settings)


@router.post("", status_code=202)
async def create_transaction(
    body: CreateTransaction,
    principal: Principal = Depends(require_officer),
    transactions=Depends(service),
):
    return public_transaction(
        await transactions.submit(
            principal.tenant_id, f"{principal.tenant_id}:{principal.role}", body
        )
    )


@router.get("/{transaction_id}")
async def get_transaction(
    transaction_id: str,
    principal: Principal = Depends(current_principal),
    transactions=Depends(service),
):
    return public_transaction(await transactions.probe(principal.tenant_id, transaction_id))


@router.post("/{transaction_id}/audit", status_code=202)
async def transaction_audit(
    transaction_id: str,
    principal: Principal = Depends(require_officer),
    transactions=Depends(service),
):
    from chainlex.api.transaction_audit import link_audit

    record = await transactions.probe(principal.tenant_id, transaction_id)
    if record["state"] != "CONFIRMED":
        raise HTTPException(409, "Confirm the settlement request before creating its audit.")
    return await link_audit(transactions.db, principal, record)
