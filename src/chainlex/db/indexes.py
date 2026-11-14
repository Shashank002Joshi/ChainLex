"""Ordinary indexes; vector definitions are provisioned separately on Atlas."""

from pymongo import ASCENDING, IndexModel

COLLECTIONS = (
    "entities",
    "regulations",
    "compliance_cases",
    "compliance_fsms",
    "agent_action_proposals",
    "policies",
    "tx_outbox",
    "audit_ledger",
    "simulator_operations",
    "tenant_controls",
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
    "compliance_fsms": [
        IndexModel([("tenant_id", 1), ("idempotency_key", 1)], unique=True, name="request_key"),
        IndexModel([("tenant_id", 1), ("fsm_id", 1)], unique=True, name="fsm_identity"),
        IndexModel([("state", 1), ("runtime.lease.expires_at", 1)], name="recoverable_fsms"),
    ],
    "agent_action_proposals": [
        IndexModel(
            [("tenant_id", 1), ("fsm_id", 1), ("version", 1)],
            unique=True,
            name="fsm_proposal_version",
        )
    ],
    "tx_outbox": [
        IndexModel([("tenant_id", 1), ("idempotency_key", 1)], unique=True, name="action_key"),
        IndexModel([("state", 1), ("next_attempt_at", 1)], name="pending_actions"),
    ],
    "audit_ledger": [
        IndexModel(
            [("tenant_id", 1), ("fsm_id", 1), ("sequence", 1)],
            unique=True,
            name="fsm_audit_sequence",
        ),
        IndexModel(
            [("tenant_id", 1), ("fsm_id", 1), ("event_id", 1)],
            unique=True,
            name="fsm_audit_event",
            partialFilterExpression={"event_id": {"$type": "string"}},
        ),
    ],
    "tenant_controls": [IndexModel([("tenant_id", 1)], unique=True, name="tenant_control")],
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


class LegacySchemaError(ValueError):
    """Bootstrap requires an explicit migration of legacy unique job indexes."""


async def bootstrap(database) -> None:
    existing = set(await database.list_collection_names())
    for name in ("agent_action_proposals", "audit_ledger"):
        if name in existing:
            async for index in await database[name].list_indexes():
                if index.get("unique") and "job_id" in index["key"]:
                    raise LegacySchemaError(
                        f"{name} has a legacy unique job_id index; plan an explicit migration "
                        "before FSM bootstrap. No legacy indexes or records were deleted."
                    )
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
