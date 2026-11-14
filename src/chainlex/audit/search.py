"""Explicit Atlas Vector Search provisioning for the audit demo."""

import json
from pathlib import Path

from pymongo.operations import SearchIndexModel


def memory_index_definition():
    return {
        "fields": [
            {
                "type": "vector",
                "path": "case_embedding",
                "numDimensions": 1024,
                "similarity": "cosine",
            },
            *[
                {"type": "filter", "path": field}
                for field in (
                    "tenant_id",
                    "scope",
                    "is_active",
                    "review_status",
                    "clearance_level",
                    "valid_from",
                    "valid_until",
                )
            ],
        ]
    }


async def provision_audit_indexes(database):
    definitions = json.loads((Path(__file__).parents[1] / "db" / "vector_indexes.json").read_text())
    specs = {
        "regulations_vector_idx": (
            "regulations",
            definitions["regulations_vector_idx"]["definition"],
        ),
        "audit_memories_idx": ("audit_memories", memory_index_definition()),
    }
    results = {}
    for name, (collection, definition) in specs.items():
        indexes = [i async for i in await database[collection].list_search_indexes()]
        existing = next((i for i in indexes if i["name"] == name), None)
        if existing:
            results[name] = {
                "status": existing.get("status"),
                "queryable": existing.get("queryable", False),
            }
            continue
        await database[collection].create_search_index(
            SearchIndexModel(
                name=name,
                definition=definition,
                type="vectorSearch",
            )
        )
        results[name] = {"status": "PROVISIONING", "queryable": False}
    return results
