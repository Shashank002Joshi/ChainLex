"""Bridge confirmed Sepolia requests to the separately implemented audit runtime."""

from copy import deepcopy

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError


async def link_audit(db, principal, transaction):
    try:
        from chainlex.audit.models import AuditRun
        from chainlex.audit.repository import AuditRepository, ledger_event
        from chainlex.audit.scenarios import scenario_input
    except ImportError as exc:
        raise HTTPException(
            503, "The three-agent audit backend is not installed in this checkout yet."
        ) from exc

    from chainlex.api.transactions import ROUTES

    tenant, actor = principal.tenant_id, f"{principal.tenant_id}:{principal.role}"
    repo = AuditRepository(db)
    await repo.ensure_tenant(tenant)
    identity = "audit-" + transaction["transaction_id"]
    if await db.compliance_fsms.find_one({"tenant_id": tenant, "fsm_id": identity}):
        return {"audit_id": identity}
    banks = [{"bank_id": b, "jurisdiction": c} for b, c in ROUTES[transaction["route_id"]]]
    source = deepcopy(scenario_input("corridor_audit"))
    explorer = f"https://sepolia.etherscan.io/tx/{transaction['tx_hash']}"
    source.update(
        {
            "amount": transaction["amount"],
            "asset": "USDC",
            "origin": banks[0]["bank_id"],
            "destination": banks[-1]["bank_id"],
            "network": "ethereum-sepolia",
            "routes": [
                {
                    "route_id": transaction["route_id"],
                    "provenance": "configured_demo_corridor",
                    "banks": banks,
                }
            ],
            "narrative": f"Sepolia settlement request {transaction['settlement_id']} for {transaction['amount']} USDC. Transaction: {explorer}. Beneficiary: {transaction['beneficiary']}. Bank relationships and compliance reasoning remain fictional demo assessments; the on-chain request receipt is real.",
            "transaction_reference": {
                "tx_hash": transaction["tx_hash"],
                "settlement_id": transaction["settlement_id"],
                "block_number": transaction["block_number"],
                "url": explorer,
            },
        }
    )
    run = AuditRun(
        audit_id=identity,
        fsm_id=identity,
        tenant_id=tenant,
        initiated_by=actor,
        clearance_level=1,
        scenario="corridor_audit",
        idempotency_key=f"sepolia:{transaction['transaction_id']}",
        checkpoint={"source": source},
    )
    event = ledger_event(
        tenant,
        identity,
        1,
        "UPSTREAM_TRANSACTION_RECEIVED",
        actor,
        "0" * 64,
        source["transaction_reference"],
    )
    run = run.model_copy(update={"last_event_hash": event["record_hash"]})

    async def save(session):
        await db.compliance_fsms.insert_one(run.model_dump(mode="python"), session=session)
        await db.audit_ledger.insert_one(dict(event), session=session)
        await db.sepolia_transactions.update_one(
            {"_id": transaction["_id"], "tenant_id": tenant},
            {"$set": {"audit_id": identity}},
            session=session,
        )

    try:
        async with db.client.start_session() as session:
            await session.with_transaction(save)
    except DuplicateKeyError:
        if await db.compliance_fsms.find_one({"tenant_id": tenant, "fsm_id": identity}) is None:
            raise HTTPException(
                409, "The transaction audit could not be linked. Retry shortly."
            ) from None
    return {"audit_id": identity}
