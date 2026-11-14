from copy import deepcopy

import eth_abi
import pytest
from pydantic import ValidationError

from chainlex.blockchain.artifacts import (
    SETTLEMENT_DETAILS_ABI_TYPE,
    TOPIC_SETTLEMENT_INITIATED_V2,
)
from chainlex.blockchain.event_bus import Web3EventBus
from chainlex.blockchain.indexer import BlockchainIndexer, decode_log
from chainlex.blockchain.semantic_search import format_tx_narrative
from chainlex.domain.settlement import RoutedSettlement, SettlementAsset
from chainlex.services.country_rules import CaseFacts


def details():
    return [
        250000000,
        "USDC",
        6,
        "0x" + "33" * 20,
        "scotiabank-jpmorgan-dbs-demo",
        ["scotiabank", "jpmorgan_chase", "dbs"],
        ["CA", "US", "SG"],
        bytes.fromhex("44" * 32),
    ]


def event(values=None, index=0):
    data = eth_abi.encode([SETTLEMENT_DETAILS_ABI_TYPE], [values or details()])
    return {
        "transactionHash": "0xtx1",
        "logIndex": index,
        "address": "0x" + "55" * 20,
        "topics": [
            TOPIC_SETTLEMENT_INITIATED_V2,
            "0x" + f"{index + 1:064x}",
            "0x" + "00" * 12 + "11" * 20,
            "0x" + "00" * 12 + "22" * 20,
        ],
        "data": "0x" + data.hex(),
    }


def test_v2_roundtrip_and_case_route():
    decoded = decode_log(event())
    assert decoded["event_name"] == "SettlementInitiated"
    assert decoded["source_event_name"] == "SettlementInitiatedV2"
    assert decoded["event_version"] == 2
    assert decoded["institution_verification"] == "UNVERIFIED"
    assert decoded["asset"]["amount_atomic"] == "250000000"
    assert decoded["asset"]["decimals"] == 6
    assert decoded["route"]["banks"][0]["bank_id"] == "scotiabank"
    case = CaseFacts(
        route=decoded["route"],
        entity_type="UNKNOWN",
        transaction_type="SETTLEMENT_REQUEST",
        narrative="New request",
    )
    assert case.applicable_jurisdictions == ("CA", "US", "SG")
    narrative = format_tx_narrative({"settlements": [decoded]})
    assert "250.000000 USDC" in narrative
    assert "scotiabank (CA) -> jpmorgan_chase (US) -> dbs (SG)" in narrative
    assert "UNVERIFIED" in narrative


@pytest.mark.parametrize(
    "position,value",
    [
        (0, 0),
        (2, 19),
        (5, ["scotiabank"]),
        (6, ["CA"]),
        (6, ["CA", "ZZ", "SG"]),
        (5, ["scotiabank", "dbs", "scotiabank"]),
        (1, "bad symbol"),
    ],
)
def test_invalid_v2_payload_is_not_dispatched(position, value):
    values = details()
    values[position] = value
    assert decode_log(event(values)) is None


def test_truncated_v2_is_not_decoded_as_default_amount_or_currency():
    log = event()
    log["data"] = "0x" + "00" * 32
    assert decode_log(log) is None
    log["data"] = "0xINVALID"
    assert decode_log(log) is None
    log = event()
    log["topics"].pop()
    assert decode_log(log) is None


def test_uint256_storage_and_exact_display():
    asset = SettlementAsset(
        amount_atomic=str(2**256 - 1), symbol="USDC", decimals=6, contract_address="0x" + "33" * 20
    )
    assert asset.display_amount().replace(".", "") == str(2**256 - 1)
    with pytest.raises(ValidationError, match="uint256"):
        asset.model_validate({**asset.model_dump(), "amount_atomic": str(2**256)})


async def test_multiple_settlements_in_one_transaction_and_event_bus_callback():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    transactions = []
    events = []

    async def capture_tx(query, update, **kwargs):
        transactions.append(deepcopy(update["$set"]))

    async def capture_event(query, update, **kwargs):
        events.append(deepcopy(update["$set"]))

    db = SimpleNamespace(
        chain_blocks=SimpleNamespace(find_one=AsyncMock(return_value=None), update_one=AsyncMock()),
        chain_transactions=SimpleNamespace(update_one=capture_tx),
        contract_events=SimpleNamespace(update_one=capture_event),
    )
    indexer = BlockchainIndexer(db, tenant_id="chainlex-demo", chain_id=11155111)
    await indexer.ingest_block(
        {"number": 100, "hash": "0xblock", "parent_hash": "0xparent", "timestamp": 1234},
        transactions=[{"hash": "0xtx1"}],
        logs=[event(index=0), event(index=1)],
    )
    tx = transactions[0]
    assert len(tx["settlements"]) == 2
    assert tx["chain_id"] == 11155111 and tx["block_hash"] == "0xblock"
    assert len(events) == 2
    assert events[0]["decoded_params"]["event_version"] == 2
    callback = AsyncMock()
    bus = Web3EventBus(db, on_settlement_initiated=callback, tenant_id="chainlex-demo")
    await bus._handle_event(events[0])
    callback.assert_awaited_once()
    decoded = callback.call_args.args[0]
    parsed = RoutedSettlement.model_validate(
        {k: v for k, v in decoded.items() if k in RoutedSettlement.model_fields}
    )
    assert parsed.route.banks[1].bank_id == "jpmorgan_chase"
