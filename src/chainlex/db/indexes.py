"""Ordinary indexes; vector definitions are provisioned separately on Atlas."""

from pymongo import ASCENDING, IndexModel

COLLECTIONS = (
    "entities",
    "regulations",
    "compliance_cases",
    "job_executions",
    "agent_action_proposals",
    "policies",
    "tx_outbox",
    "audit_ledger",
    "simulator_operations",
    "chain_blocks",
    "chain_transactions",
    "contract_events",
)

INDEXES = {
    "entities": [
        IndexModel(
            [("tenant_id", ASCENDING), ("network", ASCENDING), ("address", ASCENDING)],
            unique=True,
            name="tenant_network_address",
        )
    ],
    "job_executions": [
        IndexModel([("tenant_id", 1), ("idempotency_key", 1)], unique=True, name="request_key"),
        IndexModel([("state", 1), ("lease_expires_at", 1)], name="recoverable_jobs"),
    ],
    "agent_action_proposals": [
        IndexModel([("tenant_id", 1), ("job_id", 1), ("version", 1)], unique=True)
    ],
    "tx_outbox": [
        IndexModel([("tenant_id", 1), ("idempotency_key", 1)], unique=True, name="action_key"),
        IndexModel([("state", 1), ("next_attempt_at", 1)], name="pending_actions"),
    ],
    "audit_ledger": [IndexModel([("tenant_id", 1), ("job_id", 1), ("sequence", 1)], unique=True)],
    "simulator_operations": [
        IndexModel([("tenant_id", 1), ("idempotency_key", 1)], unique=True, name="sim_action_key")
    ],
    "chain_blocks": [
        IndexModel(
            [("tenant_id", ASCENDING), ("block_number", ASCENDING)],
            unique=True,
            name="tenant_block_unique",
        ),
        IndexModel(
            [("tenant_id", ASCENDING), ("block_hash", ASCENDING)],
            name="tenant_block_hash",
        ),
    ],
    "chain_transactions": [
        IndexModel(
            [("tenant_id", ASCENDING), ("tx_hash", ASCENDING)],
            unique=True,
            name="tenant_tx_unique",
        ),
        IndexModel(
            [("tenant_id", ASCENDING), ("block_number", ASCENDING)],
            name="tenant_tx_block",
        ),
    ],
    "contract_events": [
        IndexModel(
            [("tenant_id", ASCENDING), ("tx_hash", ASCENDING), ("log_index", ASCENDING)],
            unique=True,
            name="tenant_event_unique",
        ),
        IndexModel(
            [("tenant_id", ASCENDING), ("event_name", ASCENDING), ("is_orphaned", ASCENDING)],
            name="tenant_event_lookup",
        ),
    ],
}


async def bootstrap(database) -> None:
    existing = set(await database.list_collection_names())
    validator = {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["tenant_id", "schema_version"],
            "properties": {
                "tenant_id": {"bsonType": "string", "minLength": 1},
                "schema_version": {"bsonType": "int", "minimum": 1},
            },
        }
    }
    for name in COLLECTIONS:
        if name not in existing:
            await database.create_collection(name, validator=validator)
        else:
            await database.command({"collMod": name, "validator": validator})
        if name in INDEXES:
            await database[name].create_indexes(INDEXES[name])
