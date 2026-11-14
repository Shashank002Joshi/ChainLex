"""Preview-first manual runtime reset with atomic restoration of known demo fixtures."""

import re

from chainlex.db.seeding import fixture_documents, seed_demo

RUNTIME_COLLECTIONS = (
    "compliance_fsms",
    "agent_action_proposals",
    "tx_outbox",
    "audit_ledger",
    "simulator_operations",
)
PRESERVED = (
    "collections",
    "indexes",
    "regulations",
    "policies",
    "tenant_controls",
    "other_entity_and_case_records",
    "other_collections",
)


class SeedResetError(ValueError):
    """A seed reset target or execution request is not permitted."""


def validate_reset_target(database_name: str, *, execute: bool, confirmation: str | None) -> None:
    if len(database_name) > 63 or not re.fullmatch(
        r"chainlex_manual_[A-Za-z0-9_-]+", database_name
    ):
        raise SeedResetError("Reset is restricted to an explicit chainlex_manual_NAME database")
    if execute and confirmation != database_name:
        raise SeedResetError("Execution requires --confirm-db matching --database exactly")
    if confirmation is not None and not execute:
        raise SeedResetError("--confirm-db requires --execute")


async def _check_fixture_ownership(database, *, session=None) -> None:
    for collection, documents in fixture_documents().items():
        for document in documents:
            existing = await database[collection].find_one(
                {"_id": document["_id"]}, session=session
            )
            if existing is not None and existing.get("is_demo_fixture") is not True:
                raise SeedResetError(
                    f"Refusing to replace non-demo record {collection}/{document['_id']}"
                )


async def reset_seed_demo(
    database, *, execute: bool = False, confirmation: str | None = None
) -> dict:
    validate_reset_target(database.name, execute=execute, confirmation=confirmation)
    required = set(RUNTIME_COLLECTIONS) | set(fixture_documents())
    if (
        await database.compliance_fsms.count_documents({"workflow_type": "AUDIT"})
        or await database.audit_reports.count_documents({})
        or await database.audit_artifacts.count_documents({})
    ):
        raise SeedResetError(
            "Legacy seed reset cannot remove audit runs while preserving their reports/artifacts; "
            "use a new manual database namespace."
        )
    if not required <= set(await database.list_collection_names()):
        raise SeedResetError("Run bootstrap for the selected manual database before resetting")
    await _check_fixture_ownership(database)
    counts = {name: await database[name].count_documents({}) for name in RUNTIME_COLLECTIONS}
    if not execute:
        return {
            "database": database.name,
            "mode": "preview",
            "would_delete_runtime": counts,
            "would_restore_fixture_ids": {
                name: [document["_id"] for document in documents]
                for name, documents in fixture_documents().items()
            },
            "preserved": PRESERVED,
        }

    async with database.client.start_session() as session:
        async with await session.start_transaction():
            # Recheck inside the transaction to protect against a concurrent fixture change.
            await _check_fixture_ownership(database, session=session)
            deleted = {}
            for name in RUNTIME_COLLECTIONS:
                result = await database[name].delete_many({}, session=session)
                deleted[name] = result.deleted_count
            restored = await seed_demo(database, session=session, restore=True)
    return {
        "database": database.name,
        "mode": "reset",
        "deleted_runtime": deleted,
        "restored": restored,
        "preserved": PRESERVED,
    }
