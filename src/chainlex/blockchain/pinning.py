"""Hyperledger FireFly-Style State Pinning & Merkle Anchoring with receipt verification."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from chainlex.connectors.evm import EVMConnector


def canonical_document_hash(doc: dict[str, Any]) -> str:
    """Computes SHA-256 hash over canonical JSON payload of an audit document."""
    filtered = {k: v for k, v in doc.items() if k not in ("_id", "anchor_tx_hash", "pinned_at")}
    serialized = json.dumps(filtered, sort_keys=True, separators=(",", ":"), default=str)
    return "0x" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compute_merkle_root(hashes: list[str]) -> str:
    """Computes binary Merkle Root over a list of hex string hashes."""
    if not hashes:
        return "0x" + "00" * 32

    current = [h if h.startswith("0x") else "0x" + h for h in hashes]

    while len(current) > 1:
        next_level = []
        for i in range(0, len(current), 2):
            left = current[i]
            right = current[i + 1] if i + 1 < len(current) else left
            combined = bytes.fromhex(left[2:]) + bytes.fromhex(right[2:])
            parent = "0x" + hashlib.sha256(combined).hexdigest()
            next_level.append(parent)
        current = next_level

    return current[0]


class AuditPinService:
    """
    Batches MongoDB Atlas audit ledger records, computes their Merkle root,
    submits to SettlementHub, and verifies on-chain receipt before marking records pinned.
    """

    def __init__(self, db: Any, connector: EVMConnector, tenant_id: str = "bank_a"):
        self.db = db
        self.connector = connector
        self.tenant_id = tenant_id

    async def pin_audit_batch(self, batch_size: int = 50) -> dict[str, Any] | None:
        """
        Finds unanchored audit records, computes Merkle root, submits on-chain,
        and confirms receipt before committing anchor state.
        Never fabricates hashes or commits unverified anchors.
        """
        cursor = self.db.audit_ledger.find(
            {
                "tenant_id": self.tenant_id,
                "$or": [{"anchor_tx_hash": None}, {"anchor_tx_hash": {"$exists": False}}],
            }
        ).limit(batch_size)

        records = [doc async for doc in cursor] if hasattr(cursor, "__aiter__") else list(cursor)
        if not records:
            return None

        # Content-based hashing: never fall back to hashing document IDs
        hashes = [doc.get("record_hash") or canonical_document_hash(doc) for doc in records]
        merkle_root = compute_merkle_root(hashes)
        batch_count = len(records)

        # Pin root via EVM contract call
        call_params = [
            {
                "from": self.connector.operator_address,
                "to": self.connector.contract_address,
                "data": f"0x977db3e9{merkle_root[2:]}{batch_count:064x}",
            }
        ]

        tx_hash = await self.connector._rpc_call("eth_sendTransaction", call_params)
        if not tx_hash or not isinstance(tx_hash, str) or not tx_hash.startswith("0x"):
            raise RuntimeError(f"Audit pin failed: invalid transaction hash returned: {tx_hash}")

        # Actively verify receipt before marking records as anchored
        receipt = await self.connector._rpc_call("eth_getTransactionReceipt", [tx_hash])
        if receipt is None:
            # Broadcasted but unmined: do not claim pinned yet
            return {
                "merkle_root": merkle_root,
                "batch_count": batch_count,
                "anchor_tx_hash": tx_hash,
                "status": "PENDING",
            }

        raw_status = receipt.get("status")
        status = int(raw_status, 16) if isinstance(raw_status, str) else int(raw_status or 0)
        if status != 1:
            raise RuntimeError(f"Audit pin transaction reverted on-chain: {tx_hash}")

        # Update audit records only after receipt confirmation
        now = datetime.now(UTC)
        record_ids = [doc["_id"] for doc in records]
        await self.db.audit_ledger.update_many(
            {"tenant_id": self.tenant_id, "_id": {"$in": record_ids}},
            {"$set": {"anchor_tx_hash": tx_hash, "pinned_at": now, "merkle_root": merkle_root}},
        )

        return {
            "merkle_root": merkle_root,
            "batch_count": batch_count,
            "anchor_tx_hash": tx_hash,
            "status": "CONFIRMED",
            "pinned_at": now.isoformat(),
        }
