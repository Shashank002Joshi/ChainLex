"""Mongo-Native Blockchain Indexer with parent-hash re-organization detection."""

import logging
from typing import Any

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
    data = log.get("data", "0x")

    if event_topic == TOPIC_SETTLEMENT_INITIATED.lower():
        # topics: [event_sig, settlementId, from, to]
        # data: amountMinor (uint256), currency offset/length/string
        settlement_id = topics[1] if len(topics) > 1 else ""
        from_addr = "0x" + topics[2][-40:] if len(topics) > 2 else ""
        to_addr = "0x" + topics[3][-40:] if len(topics) > 3 else ""

        # Simple ABI decode of uint256 amountMinor if present
        amount_minor = 0
        currency = "USD"
        if len(data) >= 66:
            try:
                amount_minor = int(data[2:66], 16)
            except ValueError:
                amount_minor = 0

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
        return {
            "event_name": "SettlementFrozen",
            "settlement_id": settlement_id,
            "counterparty": counterparty,
            "operator": operator,
        }

    elif event_topic == TOPIC_AUDIT_ROOT_PINNED.lower():
        merkle_root = topics[1] if len(topics) > 1 else ""
        batch_count = 0
        if len(data) >= 66:
            try:
                batch_count = int(data[2:66], 16)
            except ValueError:
                batch_count = 0
        return {
            "event_name": "AuditRootPinned",
            "merkle_root": merkle_root,
            "batch_count": batch_count,
        }

    return None


class BlockchainIndexer:
    """Ingests blockchain data into MongoDB Atlas with parent-hash continuity checks."""

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
        Ingests a block and associated transactions/events.
        Asserts parent-hash continuity; if a fork/reorg is detected,
        orphans previous fork records.
        """
        block_num = block["number"]
        block_hash = block["hash"]
        parent_hash = block["parent_hash"]
        timestamp = block.get("timestamp", 0)

        transactions = transactions or []
        logs = logs or []

        reorg_detected = False
        reorg_block = None

        # 1. Re-organization detection: check previous block
        if block_num > 0:
            prev_block = await self.db.chain_blocks.find_one({"block_number": block_num - 1})
            if prev_block and prev_block.get("block_hash") != parent_hash:
                reorg_detected = True
                reorg_block = block_num - 1
                logger.warning(
                    f"Chain Reorganization Detected at block {reorg_block}! "
                    f"Expected parent {prev_block.get('block_hash')}, got {parent_hash}."
                )
                # Mark orphaned blocks, txs, and events
                await self.db.chain_blocks.update_many(
                    {"block_number": {"$gte": reorg_block}},
                    {"$set": {"is_orphaned": True, "is_canonical": False}},
                )
                await self.db.chain_transactions.update_many(
                    {"block_number": {"$gte": reorg_block}},
                    {"$set": {"is_orphaned": True, "is_canonical": False}},
                )
                await self.db.contract_events.update_many(
                    {"block_number": {"$gte": reorg_block}},
                    {"$set": {"is_orphaned": True}},
                )

        # 2. Ingest current block
        await self.db.chain_blocks.update_one(
            {"block_number": block_num},
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

        # 3. Ingest transactions
        for tx in transactions:
            tx_hash = tx["hash"]
            await self.db.chain_transactions.update_one(
                {"tx_hash": tx_hash},
                {
                    "$set": {
                        "tenant_id": self.tenant_id,
                        "schema_version": 1,
                        "tx_hash": tx_hash,
                        "from": tx.get("from", "").lower(),
                        "to": tx.get("to", "").lower(),
                        "value_minor": tx.get("value_minor", 0),
                        "block_number": block_num,
                        "status": tx.get("status", 1),
                        "input_data": tx.get("input_data", "0x"),
                        "is_canonical": True,
                        "is_orphaned": False,
                    }
                },
                upsert=True,
            )

        # 4. Ingest and decode contract events
        for log in logs:
            tx_hash = log.get("transactionHash", "")
            log_index = log.get("logIndex", 0)
            contract_addr = log.get("address", "").lower()
            decoded = decode_log(log)

            if decoded:
                await self.db.contract_events.update_one(
                    {"tx_hash": tx_hash, "log_index": log_index},
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
