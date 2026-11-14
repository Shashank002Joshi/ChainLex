"""EVM / Hyperledger Besu connector adhering to SettlementConnector protocol."""

import hashlib
from typing import Any

import eth_abi
import httpx

from chainlex.blockchain.artifacts import TOPIC_SETTLEMENT_FROZEN
from chainlex.connectors.simulator import prepare_action
from chainlex.domain.models import (
    DispatchReference,
    HoldAction,
    PreparedAction,
    ProbeOutcome,
    ProbeResult,
)


def _to_bytes32(val: str) -> str:
    """Pad or hash string into a 32-byte hex string (with 0x prefix)."""
    if val.startswith("0x") and len(val) == 66:
        return val.lower()
    return "0x" + hashlib.sha256(val.encode("utf-8")).hexdigest()


class EVMConnector:
    """Asynchronous EVM connector interacting with SettlementHub contract via JSON-RPC."""

    def __init__(
        self,
        rpc_url: str,
        contract_address: str,
        operator_address: str = "0xfe3b557e8fb62b89f4916b721be55ceb828dbd73",
        client: httpx.AsyncClient | None = None,
        required_confirmations: int = 1,
        outbox_collection: Any | None = None,
    ):
        self.rpc_url = rpc_url
        self.contract_address = contract_address.lower()
        self.operator_address = operator_address.lower()
        self.required_confirmations = required_confirmations
        self.outbox_collection = outbox_collection
        self._client = client
        self._owns_client = client is None

        # Fallback in-memory cache, supplemented by durable outbox_collection
        self._operation_txs: dict[str, str] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _rpc_call(self, method: str, params: list[Any]) -> Any:
        client = await self._get_client()
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }
        response = await client.post(self.rpc_url, json=payload)
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise RuntimeError(f"EVM RPC Error: {data['error']}")
        return data.get("result")

    async def prepare(self, action: HoldAction, idempotency_key: str) -> PreparedAction:
        """Deterministically prepares and hashes the action."""
        return prepare_action(action, idempotency_key)

    async def dispatch(self, prepared_action: PreparedAction) -> DispatchReference:
        """
        Encodes full calldata and dispatches freezeSettlement(bytes32,address,string)
        to the SettlementHub contract.
        Errors are never swallowed or replaced with fabricated hashes.
        """
        settlement_id_bytes32 = _to_bytes32(prepared_action.action.settlement_id)
        settlement_bytes = bytes.fromhex(settlement_id_bytes32[2:])

        # Derive target counterparty address (or pad operator if unassigned)
        counterparty_address = self.operator_address
        reason = f"Compliance hold: tenant {prepared_action.action.tenant_id}"

        # Selector: 0x1dd281a8 = freezeSettlement(bytes32,address,string)
        selector = bytes.fromhex("1dd281a8")
        encoded_args = eth_abi.encode(
            ["bytes32", "address", "string"],
            [settlement_bytes, counterparty_address, reason],
        )
        calldata = "0x" + (selector + encoded_args).hex()

        call_params = [
            {
                "from": self.operator_address,
                "to": self.contract_address,
                "data": calldata,
            }
        ]

        # Submit transaction; errors propagate directly to caller/outbox
        tx_hash = await self._rpc_call("eth_sendTransaction", call_params)
        if not tx_hash or not isinstance(tx_hash, str) or not tx_hash.startswith("0x"):
            raise RuntimeError(f"EVM RPC returned invalid transaction hash: {tx_hash}")

        # Record mapping both in-memory and durably if outbox_collection provided
        self._operation_txs[prepared_action.operation_id] = tx_hash
        if self.outbox_collection is not None:
            await self.outbox_collection.update_one(
                {
                    "tenant_id": prepared_action.action.tenant_id,
                    "operation_id": prepared_action.operation_id,
                },
                {"$set": {"tx_hash": tx_hash}},
                upsert=True,
            )

        return DispatchReference(
            operation_id=prepared_action.operation_id,
            provider="evm",
            tx_hash=tx_hash,
        )

    async def _resolve_tx_hash(self, operation_id: str, tenant_id: str) -> str | None:
        """Resolves tx_hash from in-memory cache or durable outbox collection."""
        if operation_id in self._operation_txs:
            return self._operation_txs[operation_id]
        if self.outbox_collection is not None:
            doc = await self.outbox_collection.find_one(
                {"tenant_id": tenant_id, "operation_id": operation_id}
            )
            if doc and doc.get("tx_hash"):
                self._operation_txs[operation_id] = doc["tx_hash"]
                return doc["tx_hash"]
        return None

    async def probe(self, prepared_action: PreparedAction) -> ProbeResult:
        """
        Probes on-chain state. Strictly enforces:
        1. Valid mined receipt with status == 1.
        2. Block confirmation count >= required_confirmations.
        3. Expected SettlementFrozen event log present in receipt.
        4. Contract state assertion isSettlementHeld(id) == True.
        """
        settlement_id_bytes32 = _to_bytes32(prepared_action.action.settlement_id)
        operation_id = prepared_action.operation_id
        tenant_id = prepared_action.action.tenant_id

        tx_hash = await self._resolve_tx_hash(operation_id, tenant_id)
        if not tx_hash:
            return ProbeResult(
                operation_id=operation_id,
                outcome=ProbeOutcome.NOT_FOUND,
                settlement_id=prepared_action.action.settlement_id,
            )

        # 1. Inspect transaction receipt
        try:
            receipt = await self._rpc_call("eth_getTransactionReceipt", [tx_hash])
        except Exception:
            return ProbeResult(
                operation_id=operation_id,
                outcome=ProbeOutcome.UNKNOWN,
                settlement_id=prepared_action.action.settlement_id,
            )

        if receipt is None:
            # Check if still pending in mempool
            try:
                tx_info = await self._rpc_call("eth_getTransactionByHash", [tx_hash])
                if tx_info is not None:
                    return ProbeResult(
                        operation_id=operation_id,
                        outcome=ProbeOutcome.PENDING,
                        settlement_id=prepared_action.action.settlement_id,
                    )
            except Exception:
                pass
            return ProbeResult(
                operation_id=operation_id,
                outcome=ProbeOutcome.NOT_FOUND,
                settlement_id=prepared_action.action.settlement_id,
            )

        # 2. Check receipt status
        raw_status = receipt.get("status")
        status = int(raw_status, 16) if isinstance(raw_status, str) else int(raw_status or 0)
        if status != 1:
            return ProbeResult(
                operation_id=operation_id,
                outcome=ProbeOutcome.REVERTED,
                settlement_id=prepared_action.action.settlement_id,
            )

        # 3. Check block confirmation depth
        raw_receipt_block = receipt.get("blockNumber")
        receipt_block = (
            int(raw_receipt_block, 16)
            if isinstance(raw_receipt_block, str)
            else int(raw_receipt_block or 0)
        )
        try:
            raw_current_block = await self._rpc_call("eth_blockNumber", [])
            current_block = (
                int(raw_current_block, 16)
                if isinstance(raw_current_block, str)
                else int(raw_current_block or 0)
            )
        except Exception:
            return ProbeResult(
                operation_id=operation_id,
                outcome=ProbeOutcome.UNKNOWN,
                settlement_id=prepared_action.action.settlement_id,
            )

        confirmations = max(0, current_block - receipt_block + 1)
        if confirmations < self.required_confirmations:
            return ProbeResult(
                operation_id=operation_id,
                outcome=ProbeOutcome.PENDING,
                settlement_id=prepared_action.action.settlement_id,
            )

        # 4. Check for SettlementFrozen event log in receipt
        logs = receipt.get("logs", [])
        has_freeze_log = False
        for log in logs:
            topics = [t.lower() for t in log.get("topics", [])]
            if (
                topics
                and topics[0] == TOPIC_SETTLEMENT_FROZEN.lower()
                and len(topics) > 1
                and topics[1] == settlement_id_bytes32.lower()
            ):
                has_freeze_log = True
                break

        if not has_freeze_log:
            return ProbeResult(
                operation_id=operation_id,
                outcome=ProbeOutcome.UNKNOWN,
                settlement_id=prepared_action.action.settlement_id,
            )

        # 5. Verify contract state assertion
        try:
            is_held_hex = await self._rpc_call(
                "eth_call",
                [
                    {
                        "to": self.contract_address,
                        "data": f"0xbd35afcc{settlement_id_bytes32[2:]}",
                    },
                    "latest",
                ],
            )
            if is_held_hex and int(is_held_hex, 16) == 1:
                return ProbeResult(
                    operation_id=operation_id,
                    outcome=ProbeOutcome.CONFIRMED,
                    settlement_id=prepared_action.action.settlement_id,
                    effect="HELD",
                )
        except Exception:
            pass

        return ProbeResult(
            operation_id=operation_id,
            outcome=ProbeOutcome.PENDING,
            settlement_id=prepared_action.action.settlement_id,
        )
