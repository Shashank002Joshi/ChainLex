from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from chainlex.domain.routing import (
    AllowlistEntry,
    BankAdmissionPolicy,
    RouteBank,
    SettlementRoute,
    WalletIdentity,
)
from chainlex.services.country_cli import load_bank_corpus, load_corpus
from chainlex.services.country_rules import (
    CaseFacts,
    evaluate_policies,
    retrieval_pipeline,
    retrieve_rules,
)
from chainlex.services.route_policy import evaluate_route_admission


def route():
    return SettlementRoute(
        route_id="route-1",
        banks=(
            RouteBank(bank_id="dbs", jurisdiction="SG"),
            RouteBank(bank_id="jpmorgan_chase", jurisdiction="US"),
            RouteBank(bank_id="scotiabank", jurisdiction="CA"),
        ),
    )


def wallet(address="0x1111111111111111111111111111111111111111", network="ethereum-sepolia"):
    return WalletIdentity(network=network, address=address)


def policies():
    return [
        BankAdmissionPolicy(
            policy_id=f"{bank.bank_id}-allowlist",
            tenant_id="chainlex-demo",
            bank_id=bank.bank_id,
            version=1,
            is_active=True,
            review_status="VERIFIED",
            allowed_originators=(AllowlistEntry(wallet=wallet(), label="Binance demo"),),
        )
        for bank in route().banks
    ]


def test_intermediary_country_is_in_query_retrieval_and_policy_preview():
    case = CaseFacts(
        route=route(),
        jurisdictions=("SG", "CA"),
        entity_type="MSB",
        transaction_type="VC_TRANSFER",
        narrative="Cross-border settlement",
    )
    assert case.applicable_jurisdictions == ("SG", "CA", "US")
    assert "dbs (SG) -> jpmorgan_chase (US) -> scotiabank (CA)" in case.query_text()
    query = retrieval_pipeline(case, [0.1] * 1024, "chainlex-demo", 1, datetime.now(UTC))
    assert {"jurisdiction": {"$in": ["SG", "CA", "US"]}} in (
        query[0]["$vectorSearch"]["filter"]["$and"]
    )
    _, rules = load_corpus(Path("data/country_rules"))
    result = evaluate_policies(case, rules)
    assert any(m["policy_id"].startswith("US-") for m in result["matches"])


def test_allowlisted_sender_passes_only_origin_bank_control():
    result = evaluate_route_admission(route(), wallet(), "chainlex-demo", policies())
    assert result["outcome"] == "PASS"
    assert [c["outcome"] for c in result["checks"]] == ["PASS", "NOT_APPLICABLE", "NOT_APPLICABLE"]


@pytest.mark.parametrize(
    "sender",
    [
        wallet("0x2222222222222222222222222222222222222222"),
        wallet(network="ethereum-mainnet"),
    ],
)
def test_unlisted_sender_or_wrong_network_is_denied(sender):
    result = evaluate_route_admission(route(), sender, "chainlex-demo", policies())
    assert result["outcome"] == "DENY"
    assert result["checks"][0]["reason"] == "ORIGINATOR_NOT_ALLOWLISTED"


def test_label_is_not_an_identity_and_case_is_normalized():
    rows = policies()
    rows[0] = rows[0].model_copy(
        update={
            "allowed_originators": (
                AllowlistEntry(wallet=wallet("0x" + "ab" * 20), label="Any label"),
            )
        }
    )
    sender = wallet("0x" + "AB" * 20)
    assert evaluate_route_admission(route(), sender, "chainlex-demo", rows)["outcome"] == "PASS"


def test_bank_specific_all_hops_policy_can_deny_at_intermediary():
    rows = policies()
    rows[1] = rows[1].model_copy(update={"scope": "ALL_ROUTE_POSITIONS", "allowed_originators": ()})
    result = evaluate_route_admission(route(), wallet(), "chainlex-demo", rows)
    assert result["outcome"] == "DENY"
    assert result["checks"][1]["bank_id"] == "jpmorgan_chase"
    assert result["checks"][1]["policy_version"] == 1


@pytest.mark.parametrize("change", ["missing", "inactive", "unverified", "foreign", "duplicate"])
def test_missing_or_ambiguous_policy_never_passes(change):
    rows = policies()
    if change == "missing":
        rows.pop(1)
    elif change == "duplicate":
        rows.append(rows[1].model_copy(update={"version": 2}))
    else:
        updates = {
            "inactive": {"is_active": False},
            "unverified": {"review_status": "UNVERIFIED"},
            "foreign": {"tenant_id": "other_tenant"},
        }
        rows[1] = rows[1].model_copy(update=updates[change])
    assert evaluate_route_admission(route(), wallet(), "chainlex-demo", rows)["outcome"] == "REVIEW"


def test_route_loops_rejected_and_sender_denial_overrides_missing_bank():
    with pytest.raises(ValidationError, match="loop"):
        SettlementRoute(route_id="loop", banks=(route().banks[0], route().banks[0]))
    with pytest.raises(ValidationError):
        SettlementRoute(route_id="short", banks=(route().banks[0],))
    result = evaluate_route_admission(
        route(), wallet("0x" + "22" * 20), "chainlex-demo", policies()[:1]
    )
    assert result["outcome"] == "DENY"


def test_bank_fixtures_are_inactive_and_separate_from_country_policies():
    rows = load_bank_corpus(Path("data/country_rules"))
    assert len(rows) == 3
    assert all(not p.is_active and p.review_status == "UNVERIFIED" for p in rows)
    assert "fictional" in rows[0].allowed_originators[0].label


async def test_retrieval_reserves_results_for_each_route_country():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    pipelines = []

    async def aggregate(pipeline):
        pipelines.append(pipeline)

        async def records():
            yield {"rule_id": str(len(pipelines))}

        return records()

    case = CaseFacts(
        route=route(),
        entity_type="MSB",
        transaction_type="VC_TRANSFER",
        narrative="Cross-border payment",
    )
    voyage = SimpleNamespace(embed=AsyncMock(return_value=[[0.1] * 1024] * 3))
    db = SimpleNamespace(regulations=SimpleNamespace(aggregate=aggregate))
    results = await retrieve_rules(db, voyage, case, "chainlex-demo", 1)
    assert len(results) == 3
    assert len(pipelines) == 3
    for pipeline, country in zip(pipelines, ("SG", "US", "CA"), strict=True):
        search = pipeline[0]["$vectorSearch"]
        assert {"jurisdiction": {"$in": [country]}} in search["filter"]["$and"]
        assert search["limit"] == 3
    queries, input_type = voyage.embed.call_args.args
    assert len(queries) == 3 and input_type == "query"
    assert all("jpmorgan_chase (US)" in query for query in queries)


def test_named_institution_examples_match_route_and_policy_fixtures():
    import json

    directory = Path("data/country_rules")
    institutions = {
        row["institution_id"]: row
        for row in json.loads((directory / "institutions.json").read_text())
    }
    assert institutions["wealthsimple"]["institution_type"] == "FINANCIAL_SERVICES_PLATFORM"
    fixtures = load_bank_corpus(directory)
    assert {p.bank_id for p in fixtures} == {"scotiabank", "jpmorgan_chase", "dbs"}
    reviewed = [
        p.model_copy(update={"is_active": True, "review_status": "VERIFIED"}) for p in fixtures
    ]
    examples = json.loads((directory / "route_examples.json").read_text())
    for example in examples:
        case = CaseFacts.model_validate(example["case"])
        assert set(case.applicable_jurisdictions) == {"CA", "US", "SG"}
        for bank in case.route.banks:
            assert bank.jurisdiction == institutions[bank.bank_id]["jurisdiction"]
            assert institutions[bank.bank_id]["institution_type"] == "BANK"
        sender = WalletIdentity.model_validate(example["originator"]["wallet"])
        result = evaluate_route_admission(case.route, sender, "chainlex-demo", reviewed)
        assert result["outcome"] == "PASS"
