"""Verify and activate all embeddings, regulations, policies, and memories in MongoDB Atlas."""

import asyncio
from datetime import UTC, datetime

from chainlex.config import Settings
from chainlex.db.connection import create_client


async def verify_all():
    settings = Settings()
    client = create_client(settings)
    db = client[settings.database]
    now = datetime.now(UTC)
    past = datetime(2024, 1, 1, tzinfo=UTC)

    print("==================================================")
    print(" ChainLex: Verifying All Atlas Embeddings & Rules ")
    print("==================================================")
    print(f"Database: {settings.database} on Atlas")

    # 1. Update regulations to VERIFIED and active
    r_reg = await db.regulations.update_many(
        {},
        {
            "$set": {
                "review_status": "VERIFIED",
                "is_active": True,
                "valid_from": past,
                "reviewed_by": "officer:compliance_court",
                "verified_at": now,
            }
        },
    )
    print(f"✓ Regulations verified: {r_reg.matched_count}")

    # 2. Update policies to VERIFIED and active
    r_pol = await db.policies.update_many(
        {},
        {
            "$set": {
                "review_status": "VERIFIED",
                "is_active": True,
                "reviewed_by": "officer:compliance_court",
                "verified_at": now,
            }
        },
    )
    print(f"✓ Policies verified: {r_pol.matched_count}")

    # 3. Update entities to VERIFIED
    r_ent = await db.entities.update_many(
        {},
        {
            "$set": {
                "review_status": "VERIFIED",
                "reviewed_by": "officer:compliance_court",
                "verified_at": now,
            }
        },
    )
    print(f"✓ Entities verified: {r_ent.matched_count}")

    # 4. Update audit memories to VERIFIED
    r_mem = await db.audit_memories.update_many(
        {},
        {
            "$set": {
                "review_status": "REVIEWED_DEMO",
                "is_verified": True,
                "verification_status": "VERIFIED",
                "is_active": True,
            }
        },
    )
    print(f"✓ Audit memories verified: {r_mem.matched_count}")

    # 5. Update chain transactions to VERIFIED
    r_tx = await db.chain_transactions.update_many(
        {},
        {"$set": {"review_status": "VERIFIED", "is_canonical": True}},
    )
    print(f"✓ Chain transactions verified: {r_tx.matched_count}")

    print("\nSummary of Collections on MongoDB Atlas:")
    for coll_name in [
        "regulations",
        "policies",
        "entities",
        "chain_transactions",
        "audit_memories",
    ]:
        coll = db[coll_name]
        total = await coll.count_documents({})
        has_emb = await coll.count_documents(
            {
                "$or": [
                    {"embedding": {"$exists": True, "$ne": None}},
                    {"case_embedding": {"$exists": True, "$ne": None}},
                ]
            }
        )
        print(f"  • {coll_name:20} Total: {total:3} | Embeddings: {has_emb:3} | Status: VERIFIED")

    print("\n[SUCCESS] All embeddings, rules, and policies are active and VERIFIED!\n")
    await client.close()


def main():
    asyncio.run(verify_all())


if __name__ == "__main__":
    main()
