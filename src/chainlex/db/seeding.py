"""Canonical demo fixtures and idempotent writes shared by normal and reset seeding."""


def fixture_documents() -> dict[str, list[dict]]:
    entities = []
    cases = []
    for index in range(6):
        entities.append(
            {
                "_id": f"demo-entity-{index + 1}",
                "tenant_id": "bank_a" if index < 3 else "bank_b",
                "schema_version": 1,
                "network": "simulation",
                "address": f"0x{index + 1:040x}",
                "label": f"Fictional Demo Counterparty {index + 1}",
                "jurisdiction": "USA" if index % 2 == 0 else "SGP",
                "is_demo_fixture": True,
                "review_status": "UNVERIFIED",
            }
        )
    for index in range(4):
        cases.append(
            {
                "_id": f"demo-case-{index + 1}",
                "tenant_id": "bank_a" if index < 2 else "bank_b",
                "schema_version": 1,
                "is_demo_fixture": True,
                "review_status": "UNVERIFIED",
                "is_active": False,
                "narrative": "Fictional precedent fixture; no legal finding or regulatory filing.",
            }
        )
    return {"entities": entities, "compliance_cases": cases}


async def seed_demo(database, *, session=None, restore: bool = False) -> dict:
    for collection, documents in fixture_documents().items():
        for document in documents:
            if restore:
                await database[collection].replace_one(
                    {"_id": document["_id"], "is_demo_fixture": True},
                    document,
                    upsert=True,
                    session=session,
                )
            else:
                await database[collection].update_one(
                    {"_id": document["_id"]},
                    {"$setOnInsert": document},
                    upsert=True,
                    session=session,
                )
    return {"entities": 6, "cases": 4, "review_status": "UNVERIFIED"}
