"""Deterministic route admission; callers must authenticate the sender wallet."""

from chainlex.domain.routing import BankAdmissionPolicy, SettlementRoute, WalletIdentity


def evaluate_route_admission(
    route: SettlementRoute,
    authenticated_originator: WalletIdentity,
    tenant_id: str,
    policies: list[BankAdmissionPolicy],
) -> dict:
    """Check every route bank; one denial overrides any review or local pass.

    The authenticated wallet must come from signature verification or a trusted
    custody identity service, never a self-reported exchange name or request body.
    PASS only covers these bank admission controls, not regulatory clearance.
    """
    if not tenant_id:
        raise ValueError("Authenticated tenant is required")
    checks = []
    for position, bank in enumerate(route.banks):
        candidates = [
            p
            for p in policies
            if p.tenant_id == tenant_id
            and p.bank_id == bank.bank_id
            and p.is_active
            and p.review_status == "VERIFIED"
        ]
        base = {"bank_id": bank.bank_id, "position": position}
        if len(candidates) != 1:
            checks.append({**base, "outcome": "REVIEW", "reason": "MISSING_OR_AMBIGUOUS_POLICY"})
            continue
        policy = candidates[0]
        base.update({"policy_id": policy.policy_id, "policy_version": policy.version})
        if position > 0 and policy.scope == "ORIGINATING_BANK":
            checks.append(
                {**base, "outcome": "NOT_APPLICABLE", "reason": "ORIGINATOR_CHECK_ONLY_AT_SOURCE"}
            )
            continue
        allowed = any(
            entry.wallet == authenticated_originator for entry in policy.allowed_originators
        )
        checks.append(
            {
                **base,
                "outcome": "PASS" if allowed else "DENY",
                "reason": "ORIGINATOR_ALLOWLISTED" if allowed else "ORIGINATOR_NOT_ALLOWLISTED",
            }
        )
    outcomes = {check["outcome"] for check in checks}
    outcome = "DENY" if "DENY" in outcomes else "REVIEW" if "REVIEW" in outcomes else "PASS"
    return {"route_id": route.route_id, "outcome": outcome, "checks": checks}


async def load_bank_policies(db, route: SettlementRoute, tenant_id: str):
    """Tenant-owned policy registry; route bank IDs never grant another tenant's access."""
    cursor = db.policies.find(
        {
            "tenant_id": tenant_id,
            "bank_id": {"$in": [bank.bank_id for bank in route.banks]},
            "policy_type": "BANK_ORIGINATOR_ALLOWLIST",
            "is_active": True,
            "review_status": "VERIFIED",
        }
    )
    # MongoDB metadata is excluded from the strict domain contract explicitly.
    fields = BankAdmissionPolicy.model_fields
    return [
        BankAdmissionPolicy.model_validate({k: v for k, v in doc.items() if k in fields})
        async for doc in cursor
    ]
