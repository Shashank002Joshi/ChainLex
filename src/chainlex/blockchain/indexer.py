"""Mongo-Native Blockchain Indexer with same-height and multi-block re-org detection."""

import logging
from typing import Any

import eth_abi

from chainlex.blockchain.artifacts import (
    TOPIC_AUDIT_ROOT_PINNED,
    TOPIC_SETTLEMENT_FROZEN,
    TOPIC_SETTLEMENT_INITIATED,
)

logger = logging.getLogger(__name__)


def decode_log(log: dict[str, Any]) -> dict[str, Any] | None:
    """Decodes raw Ethereum log topics and data into typed event representations."""
    topics = log.get("topics", [])
    if not topics:
        return None

    event_topic = topics[0].lower()
    raw_data = log.get("data", "0x")
    data_bytes = (
        bytes.fromhex(raw_data[2:]) if raw_data.startswith("0x") else bytes.fromhex(raw_data)
    )

    if event_topic == TOPIC_SETTLEMENT_INITIATED.lower():
        # topics: [event_sig, settlementId, from, to]
        settlement_id = topics[1] if len(topics) > 1 else ""
        from_addr = "0x" + topics[2][-40:] if len(topics) > 2 else ""
        to_addr = "0x" + topics[3][-40:] if len(topics) > 3 else ""

        amount_minor = 0
        currency = "USD"
        if data_bytes:
            try:
                decoded_data = eth_abi.decode(["uint256", "string"], data_bytes)
                amount_minor = decoded_data[0]
                currency = decoded_data[1]
            except Exception:
                if len(data_bytes) >= 32:
                    amount_minor = int.from_bytes(data_bytes[:32], "big")

        return {
            "event_name": "SettlementInitiated",
            "settlement_id": settlement_id,
            "from_address": from_addr,
            "to_address": to_addr,
            "amount_minor": amount_minor,
            "currency": currency,
        }

    elif event_topic == TOPIC_SETTLEMENT_FROZEN.lower():
        settlement_id = topics[1] if len(topics) > 1 else ""
        counterparty = "0x" + topics[2][-40:] if len(topics) > 2 else ""
        operator = "0x" + topics[3][-40:] if len(topics) > 3 else ""
        reason = ""
        if data_bytes:
            try:
                reason = eth_abi.decode(["string"], data_bytes)[0]
            except Exception:
                pass

        return {
            "event_name": "SettlementFrozen",
            "settlement_id": settlement_id,
            "counterparty": counterparty,
            "operator": operator,
            "reason": reason,
        }

    elif event_topic == TOPIC_AUDIT_ROOT_PINNED.lower():
        merkle_root = topics[1] if len(topics) > 1 else ""
        batch_count = 0
        timestamp = 0
        if data_bytes:
            try:
                decoded = eth_abi.decode(["uint256", "uint256"], data_bytes)
                batch_count = decoded[0]
                timestamp = decoded[1]
            except Exception:
                if len(data_bytes) >= 32:
                    batch_count = int.from_bytes(data_bytes[:32], "big")

        return {
            "event_name": "AuditRootPinned",
            "merkle_root": merkle_root,
            "batch_count": batch_count,
            "timestamp": timestamp,
        }

    return None


class BlockchainIndexer:
    """Ingests blockchain data into MongoDB Atlas with tenant isolation and re-org resilience."""

    def __init__(self, db: Any, tenant_id: str = "bank_a"):
        self.db = db
        self.tenant_id = tenant_id

    async def ingest_block(
        self,
        block: dict[str, Any],
        transactions: list[dict[str, Any]] | None = None,
        logs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Ingests a block and associated transactions/events scoped strictly by tenant.
        Detects both multi-block parent mismatches and same-height sibling forks.
        """
        block_num = block["number"]
        block_hash = block["hash"]
        parent_hash = block["parent_hash"]
        timestamp = block.get("timestamp", 0)

        transactions = transactions or []
        logs = logs or []

        reorg_detected = False
        reorg_block = None

        # 1. Same-height reorganization detection (sibling block replacement)
        existing_at_height = await self.db.chain_blocks.find_one(
            {"tenant_id": self.tenant_id, "block_number": block_num}
        )
        if existing_at_height and existing_at_height.get("block_hash") != block_hash:
            reorg_detected = True
            reorg_block = block_num
            logger.warning(
                f"Same-height fork at block {block_num}! Existing "
                f"{existing_at_height.get('block_hash')}, incoming {block_hash}."
            )

        # 2. Multi-block parent continuity check
        if not reorg_detected and block_num > 0:
            prev_block = await self.db.chain_blocks.find_one(
                {"tenant_id": self.tenant_id, "block_number": block_num - 1}
            )
            if prev_block and prev_block.get("block_hash") != parent_hash:
                reorg_detected = True
                reorg_block = block_num - 1
                logger.warning(
                    f"Chain parent mismatch at block {reorg_block}! Expected parent "
                    f"{prev_block.get('block_hash')}, got {parent_hash}."
                )

        # Orphan any conflicting chain state for this tenant
        if reorg_detected and reorg_block is not None:
            await self.db.chain_blocks.update_many(
                {"tenant_id": self.tenant_id, "block_number": {"$gte": reorg_block}},
                {"$set": {"is_orphaned": True, "is_canonical": False}},
            )
            await self.db.chain_transactions.update_many(
                {"tenant_id": self.tenant_id, "block_number": {"$gte": reorg_block}},
                {"$set": {"is_orphaned": True, "is_canonical": False}},
            )
            await self.db.contract_events.update_many(
                {"tenant_id": self.tenant_id, "block_number": {"$gte": reorg_block}},
                {"$set": {"is_orphaned": True}},
            )

        # 3. Ingest current block scoped by tenant_id
        await self.db.chain_blocks.update_one(
            {"tenant_id": self.tenant_id, "block_number": block_num},
            {
                "$set": {
                    "tenant_id": self.tenant_id,
                    "schema_version": 1,
                    "block_number": block_num,
                    "block_hash": block_hash,
                    "parent_hash": parent_hash,
                    "timestamp": timestamp,
                    "is_canonical": True,
                    "is_orphaned": False,
                }
            },
            upsert=True,
        )

        # 4. Ingest transactions scoped by tenant_id
        for tx in transactions:
            tx_hash = tx["hash"]
            await self.db.chain_transactions.update_one(
                {"tenant_id": self.tenant_id, "tx_hash": tx_hash},
                {
                    "$set": {
                        "tenant_id": self.tenant_id,
                        "schema_version": 1,
                        "tx_hash": tx_hash,
                        "from": tx.get("from", "").lower(),
                        "to": tx.get("to", "").lower(),
                        "value_minor": tx.get("value_minor", 0),
                        "currency": tx.get("currency", "USD"),
                        "block_number": block_num,
                        "status": tx.get("status", 1),
                        "input_data": tx.get("input_data", "0x"),
                        "is_canonical": True,
                        "is_orphaned": False,
                    }
                },
                upsert=True,
            )

        # 5. Ingest decoded contract events scoped by tenant_id
        for log in logs:
            tx_hash = log.get("transactionHash", "")
            log_index = log.get("logIndex", 0)
            contract_addr = log.get("address", "").lower()
            decoded = decode_log(log)

            if decoded:
                await self.db.contract_events.update_one(
                    {"tenant_id": self.tenant_id, "tx_hash": tx_hash, "log_index": log_index},
                    {
                        "$set": {
                            "tenant_id": self.tenant_id,
                            "schema_version": 1,
                            "tx_hash": tx_hash,
                            "log_index": log_index,
                            "contract_address": contract_addr,
                            "event_name": decoded["event_name"],
                            "decoded_params": decoded,
                            "block_number": block_num,
                            "is_orphaned": False,
                        }
                    },
                    upsert=True,
                )

        return {
            "block_number": block_num,
            "block_hash": block_hash,
            "tx_count": len(transactions),
            "event_count": len(logs),
            "reorg_detected": reorg_detected,
            "reorg_block": reorg_block,
        }
