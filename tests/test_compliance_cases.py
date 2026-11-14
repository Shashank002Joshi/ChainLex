"""Comprehensive validation of the three core compliance scenarios:

1. Cross-country trans-jurisdictional compliance (CA -> US -> SG).
2. Internal bank transfers preventing Binance-like hacks
   (unauthorized sweeps, wash trades, commingling).
3. Multihop correspondent banking routing decided based on policy rules.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import eth_abi
import httpx
import pytest
from pydantic import ValidationError

from chainlex.blockchain.artifacts import (
    SETTLEMENT_DETAILS_ABI_TYPE,
    TOPIC_SETTLEMENT_INITIATED_V2,
)
from chainlex.blockchain.indexer import BlockchainIndexer, decode_log
from chainlex.blockchain.semantic_search import format_tx_narrative
from chainlex.connectors.evm import EVMConnector
from chainlex.domain.models import HoldAction, ProbeOutcome
from chainlex.domain.routing import (
    AllowlistEntry,
    BankAdmissionPolicy,
    RouteBank,
    SettlementRoute,
    WalletIdentity,
)
from chainlex.domain.settlement import RoutedSettlement, SettlementAsset
from chainlex.services.country_cli import load_bank_corpus, load_corpus
from chainlex.services.country_rules import CaseFacts, evaluate_policies
from chainlex.services.route_policy import evaluate_route_admission

CORPUS_DIR = Path("data/country_rules")


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------


def make_wallet(
    address: str = "0x1111111111111111111111111111111111111111",
    network: str = "ethereum-sepolia",
) -> WalletIdentity:
    return WalletIdentity(network=network, address=address)


def make_multihop_route(
    origin: str = "scotiabank",
    origin_country: str = "CA",
    intermediary: str = "jpmorgan_chase",
    inter_country: str = "US",
    destination: str = "dbs",
    dest_country: str = "SG",
) -> SettlementRoute:
    return SettlementRoute(
        route_id=f"{origin}-{intermediary}-{destination}-corridor",
        banks=(
            RouteBank(bank_id=origin, jurisdiction=origin_country),
            RouteBank(bank_id=intermediary, jurisdiction=inter_country),
            RouteBank(bank_id=destination, jurisdiction=dest_country),
        ),
    )


def make_v2_log(
    settlement_id: str,
    initiator: str,
    beneficiary: str,
    amount_atomic: int = 250000000,
    symbol: str = "USDC",
    decimals: int = 6,
    banks: list[str] | None = None,
    countries: list[str] | None = None,
    instructions_hash: bytes | None = None,
    tx_hash: str = "0xtx_case_1",
    log_index: int = 0,
) -> dict:
    banks = banks or ["scotiabank", "jpmorgan_chase", "dbs"]
    countries = countries or ["CA", "US", "SG"]
    instructions_hash = instructions_hash or bytes.fromhex("44" * 32)
    details = [
        amount_atomic,
        symbol,
        decimals,
        "0x" + "33" * 20,
        "corridor-demo-route",
        banks,
        countries,
        instructions_hash,
    ]
    data = eth_abi.encode([SETTLEMENT_DETAILS_ABI_TYPE], [details])
    return {
        "transactionHash": tx_hash,
        "logIndex": log_index,
        "address": "0x" + "55" * 20,
        "topics": [
            TOPIC_SETTLEMENT_INITIATED_V2,
            settlement_id,
            "0x" + "00" * 12 + initiator.removeprefix("0x"),
            "0x" + "00" * 12 + beneficiary.removeprefix("0x"),
        ],
        "data": "0x" + data.hex(),
    }


# ---------------------------------------------------------------------------
# CASE 1: Cross-Country Settlement Compliance (CA -> US -> SG)
# ---------------------------------------------------------------------------


class TestCase1CrossCountryCompliance:
    """Verifies that cross-country multi-jurisdiction rules (FINTRAC, OFAC, MAS)

    are accurately identified, combined, and evaluated without omitting intermediary laws.
    """

    def test_cross_country_jurisdiction_aggregation(self):
        """Cross-border route aggregates all route countries into legal scope."""
        route = make_multihop_route()
        case = CaseFacts(
            route=route,
            entity_type="FINANCIAL_SERVICES_PLATFORM",
            transaction_type="CROSS_BORDER_SETTLEMENT_REQUEST",
            narrative="Settlement from Canada to Singapore transiting US correspondent system",
        )
        assert case.applicable_jurisdictions == ("CA", "US", "SG")
        assert "scotiabank (CA) -> jpmorgan_chase (US) -> dbs (SG)" in case.query_text()

    def test_cross_country_missing_travel_rule_triggers_review(self):
        """Cross-border settlement lacking Travel Rule triggers REVIEW with citations."""
        route = make_multihop_route()
        case = CaseFacts(
            route=route,
            entity_type="FINANCIAL_SERVICES_PLATFORM",
            transaction_type="CROSS_BORDER_SETTLEMENT_REQUEST",
            narrative="Cross-border wire exceeding reporting threshold",
            travel_rule_complete=False,  # Fails Canadian FINTRAC / FinCEN Travel Rule
            sanctions_clear=True,
            cdd_complete=True,
        )
        _, policies = load_corpus(CORPUS_DIR)
        result = evaluate_policies(case, policies)

        assert result["outcome"] == "REVIEW"
        reasons = [m["reason"] for m in result["matches"]]
        assert "CONTROL_NOT_SATISFIED" in reasons
        ca_matches = [
            m for m in result["matches"] if "CA-FINTRAC-TRAVEL-001" in m["source_rule_ids"]
        ]
        assert len(ca_matches) > 0

    def test_cross_country_missing_mas_cdd_triggers_review(self):
        """Cross-border settlement to Singapore lacking CDD triggers MAS review."""
        route = make_multihop_route()
        case = CaseFacts(
            route=route,
            entity_type="EXCHANGE",
            transaction_type="CROSS_BORDER_SETTLEMENT_REQUEST",
            narrative="Inbound transfer to Singapore DPT recipient",
            travel_rule_complete=True,
            sanctions_clear=True,
            cdd_complete=False,  # Fails MAS PSN02 CDD
        )
        _, policies = load_corpus(CORPUS_DIR)
        result = evaluate_policies(case, policies)

        assert result["outcome"] == "REVIEW"
        sg_matches = [m for m in result["matches"] if "SG-MAS-CDD-001" in m["source_rule_ids"]]
        assert len(sg_matches) > 0

    def test_cross_country_fully_compliant_passes(self):
        """When regulatory controls across CA, US, SG are verified, outcome is clean."""
        route = make_multihop_route()
        case = CaseFacts(
            route=route,
            entity_type="BANK",
            transaction_type="CROSS_BORDER_SETTLEMENT_REQUEST",
            narrative="Fully documented cross-border institutional settlement",
            cdd_complete=True,
            travel_rule_complete=True,
            sanctions_clear=True,
            monitoring_review_complete=True,
            recordkeeping_complete=True,
            reporting_review_complete=True,
            licensing_review_complete=True,
            risk_assessment_complete=True,
            beneficial_ownership_checked=True,
        )
        _, policies = load_corpus(CORPUS_DIR)
        result = evaluate_policies(case, policies)
        assert result["outcome"] == "NO_MATCH"
        assert result["matches"] == []

    @pytest.mark.asyncio
    async def test_cross_country_indexer_event_and_narrative(self):
        """Indexer decodes V2 cross-country event and formats multi-jurisdiction narrative."""
        log = make_v2_log(
            settlement_id="0x" + "01" * 32,
            initiator="0x1111111111111111111111111111111111111111",
            beneficiary="0x2222222222222222222222222222222222222222",
            amount_atomic=500_000_000_000,  # 500,000.00 USDC
            decimals=6,
            symbol="USDC",
        )
        decoded = decode_log(log)
        assert decoded is not None
        assert decoded["event_name"] == "SettlementInitiated"
        assert decoded["event_version"] == 2
        assert decoded["route"]["banks"][0]["jurisdiction"] == "CA"
        assert decoded["route"]["banks"][1]["jurisdiction"] == "US"
        assert decoded["route"]["banks"][2]["jurisdiction"] == "SG"

        narrative = format_tx_narrative({"settlements": [decoded]})
        assert "500000.000000 USDC" in narrative
        assert "scotiabank (CA) -> jpmorgan_chase (US) -> dbs (SG)" in narrative
        assert "UNVERIFIED" in narrative


# ---------------------------------------------------------------------------
# CASE 2: Internal Bank Transfers & Binance-like Hack Prevention
# ---------------------------------------------------------------------------


class TestCase2InternalBankBinancePrevention:
    """Verifies safeguards against Binance/FTX-style hacks:

    - Unauthorized hot wallet / rogue employee internal sweeps
    - Cross-network spoofing
    - Commingling customer funds without beneficial ownership
    - Wash trading / self-settlements
    - Unanchored zero-hash settlements
    - Protective automated on-chain freezing
    """

    def test_rogue_unlisted_originator_denied(self):
        """An unallowlisted rogue hot wallet attempting an internal sweep is immediately DENIED."""
        route = make_multihop_route()
        rogue_sender = make_wallet("0x9999999999999999999999999999999999999999")
        bank_policies = load_bank_corpus(CORPUS_DIR)

        # Activate bank policies for the test
        active_policies = [
            p.model_copy(update={"is_active": True, "review_status": "VERIFIED"})
            for p in bank_policies
        ]

        result = evaluate_route_admission(route, rogue_sender, "chainlex-demo", active_policies)
        assert result["outcome"] == "DENY"
        origin_check = result["checks"][0]
        assert origin_check["outcome"] == "DENY"
        assert origin_check["reason"] == "ORIGINATOR_NOT_ALLOWLISTED"

    def test_cross_network_spoofing_denied(self):
        """A valid bank address submitted on an unauthorized network is DENIED."""
        route = make_multihop_route()
        # Legitimate address, but unauthorized network
        spoofed_sender = make_wallet(
            "0x1111111111111111111111111111111111111111", network="ethereum-mainnet"
        )
        bank_policies = load_bank_corpus(CORPUS_DIR)
        active_policies = [
            p.model_copy(update={"is_active": True, "review_status": "VERIFIED"})
            for p in bank_policies
        ]

        result = evaluate_route_admission(route, spoofed_sender, "chainlex-demo", active_policies)
        assert result["outcome"] == "DENY"
        assert result["checks"][0]["outcome"] == "DENY"

    def test_commingled_sweep_without_beneficial_ownership_triggers_review(self):
        """Internal omnibus transfer without verified beneficial ownership triggers REVIEW."""
        route = make_multihop_route()
        case = CaseFacts(
            route=route,
            entity_type="EXCHANGE",
            transaction_type="INTERNAL_OMNIBUS_SWEEP",
            narrative="Omnibus customer sweep to proprietary omnibus account",
            beneficial_ownership_checked=False,  # Unverified beneficial ownership!
            cdd_complete=True,
            sanctions_clear=True,
        )
        _, policies = load_corpus(CORPUS_DIR)
        result = evaluate_policies(case, policies)
        assert result["outcome"] == "REVIEW"
        assert any(m["reason"] == "CONTROL_NOT_SATISFIED" for m in result["matches"])

    def test_self_settlement_wash_trading_rejected_by_domain(self):
        """Initiator matching beneficiary (wash trading / circular sweep) is rejected."""
        same_wallet = "0x" + "11" * 20
        with pytest.raises(ValidationError, match="Self-settlement prohibited"):
            RoutedSettlement(
                settlement_id="0x" + "01" * 32,
                initiator_wallet=same_wallet,
                beneficiary_wallet=same_wallet,
                asset=SettlementAsset(
                    amount_atomic="1000000",
                    symbol="USDC",
                    decimals=6,
                    contract_address="0x" + "33" * 20,
                ),
                route=make_multihop_route(),
                instructions_hash="0x" + "44" * 32,
            )

    def test_zero_instructions_hash_rejected_by_domain(self):
        """Settlement attempting to evade Travel Rule off-chain commitment is rejected."""
        zero_hash = "0x" + "00" * 32
        with pytest.raises(ValidationError, match="instructions hash must be nonzero"):
            RoutedSettlement(
                settlement_id="0x" + "01" * 32,
                initiator_wallet="0x" + "11" * 20,
                beneficiary_wallet="0x" + "22" * 20,
                asset=SettlementAsset(
                    amount_atomic="1000000",
                    symbol="USDC",
                    decimals=6,
                    contract_address="0x" + "33" * 20,
                ),
                route=make_multihop_route(),
                instructions_hash=zero_hash,
            )

    @pytest.mark.asyncio
    async def test_protective_on_chain_freeze_execution(self):
        """When an internal Binance-like breach is identified, EVMConnector executes freeze."""

        def rpc_handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            method = body.get("method")
            if method == "eth_sendTransaction":
                return httpx.Response(
                    200, json={"jsonrpc": "2.0", "id": 1, "result": "0xfreeze_tx_hash_123"}
                )
            elif method == "eth_getTransactionReceipt":
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "blockNumber": "0x64",
                            "status": "0x1",
                            "logs": [
                                {
                                    "topics": [
                                        "0x895c23d9d6c477b4e6107f27719bc987e6199ae8f1db3780923d7cb978a303d5",
                                        "0x" + "01" * 32,
                                    ]
                                }
                            ],
                        },
                    },
                )
            elif method == "eth_blockNumber":
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x66"})
            elif method == "eth_call":
                return httpx.Response(
                    200, json={"jsonrpc": "2.0", "id": 1, "result": "0x" + "00" * 31 + "01"}
                )
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": None})

        client = httpx.AsyncClient(transport=httpx.MockTransport(rpc_handler))
        connector = EVMConnector(
            rpc_url="http://127.0.0.1:8545",
            contract_address="0x1111111111111111111111111111111111111111",
            client=client,
            required_confirmations=1,
        )

        action = HoldAction(
            tenant_id="bank_a",
            settlement_id="0x" + "01" * 32,
            amount_minor=1000000,
        )
        prepared = await connector.prepare(action, "idemp-freeze-1")
        ref = await connector.dispatch(prepared)

        assert ref.tx_hash == "0xfreeze_tx_hash_123"

        probe = await connector.probe(prepared)
        assert probe.outcome == ProbeOutcome.CONFIRMED
        assert probe.effect == "HELD"
        await connector.close()


# ---------------------------------------------------------------------------
# CASE 3: Routing With Multihop Correspondent Banks Decided Based on Rules
# ---------------------------------------------------------------------------


class TestCase3MultihopCorrespondentRouting:
    """Verifies that multi-hop correspondent routes (Origin -> Intermediaries -> Destination)

    are governed strictly by each participant bank's scope and admission rules.
    """

    def test_multihop_origin_allowed_intermediary_trusts_origin(self):
        """When intermediary banks use ORIGINATING_BANK scope, they trust the originating bank."""
        route = make_multihop_route()
        originator = make_wallet("0x1111111111111111111111111111111111111111")
        bank_policies = [
            BankAdmissionPolicy(
                policy_id=f"{b.bank_id}-policy",
                tenant_id="chainlex-demo",
                bank_id=b.bank_id,
                version=1,
                scope="ORIGINATING_BANK",
                is_active=True,
                review_status="VERIFIED",
                allowed_originators=(AllowlistEntry(wallet=originator, label="Approved"),),
            )
            for b in route.banks
        ]

        result = evaluate_route_admission(route, originator, "chainlex-demo", bank_policies)
        assert result["outcome"] == "PASS"
        assert result["checks"][0]["outcome"] == "PASS"
        assert result["checks"][1]["outcome"] == "NOT_APPLICABLE"
        assert result["checks"][2]["outcome"] == "NOT_APPLICABLE"

    def test_multihop_strict_intermediary_all_positions_denies_unlisted_sender(self):
        """When an intermediary enforces ALL_ROUTE_POSITIONS, unlisted sender is DENIED."""
        route = make_multihop_route()
        originator = make_wallet("0x1111111111111111111111111111111111111111")
        other_wallet = make_wallet("0x3333333333333333333333333333333333333333")

        policies = [
            # Origin bank allows originator
            BankAdmissionPolicy(
                policy_id="scotiabank-policy",
                tenant_id="chainlex-demo",
                bank_id="scotiabank",
                version=1,
                scope="ORIGINATING_BANK",
                is_active=True,
                review_status="VERIFIED",
                allowed_originators=(
                    AllowlistEntry(wallet=originator, label="Approved at origin"),
                ),
            ),
            # Intermediary bank (JPMorgan) has strict ALL_ROUTE_POSITIONS, only allows other_wallet!
            BankAdmissionPolicy(
                policy_id="jpmorgan-policy",
                tenant_id="chainlex-demo",
                bank_id="jpmorgan_chase",
                version=1,
                scope="ALL_ROUTE_POSITIONS",
                is_active=True,
                review_status="VERIFIED",
                allowed_originators=(
                    AllowlistEntry(wallet=other_wallet, label="Only institutional partner"),
                ),
            ),
            # Destination bank
            BankAdmissionPolicy(
                policy_id="dbs-policy",
                tenant_id="chainlex-demo",
                bank_id="dbs",
                version=1,
                scope="ORIGINATING_BANK",
                is_active=True,
                review_status="VERIFIED",
                allowed_originators=(),
            ),
        ]

        result = evaluate_route_admission(route, originator, "chainlex-demo", policies)
        # Intermediary position 1 strictly DENIED the route!
        assert result["outcome"] == "DENY"
        assert result["checks"][0]["outcome"] == "PASS"
        assert result["checks"][1]["outcome"] == "DENY"
        assert result["checks"][1]["reason"] == "ORIGINATOR_NOT_ALLOWLISTED"

    def test_multihop_missing_intermediary_policy_triggers_review(self):
        """If an intermediary bank has an unverified or missing policy, route triggers REVIEW."""
        route = make_multihop_route()
        originator = make_wallet("0x1111111111111111111111111111111111111111")

        # Provide policy only for origin and destination; intermediary jpmorgan is missing!
        partial_policies = [
            BankAdmissionPolicy(
                policy_id="scotiabank-policy",
                tenant_id="chainlex-demo",
                bank_id="scotiabank",
                version=1,
                scope="ORIGINATING_BANK",
                is_active=True,
                review_status="VERIFIED",
                allowed_originators=(AllowlistEntry(wallet=originator),),
            ),
            BankAdmissionPolicy(
                policy_id="dbs-policy",
                tenant_id="chainlex-demo",
                bank_id="dbs",
                version=1,
                scope="ORIGINATING_BANK",
                is_active=True,
                review_status="VERIFIED",
                allowed_originators=(),
            ),
        ]

        result = evaluate_route_admission(route, originator, "chainlex-demo", partial_policies)
        assert result["outcome"] == "REVIEW"
        assert result["checks"][1]["outcome"] == "REVIEW"
        assert result["checks"][1]["reason"] == "MISSING_OR_AMBIGUOUS_POLICY"

    def test_multihop_routing_loop_rejected(self):
        """A corridor containing a repeated bank (routing loop: A -> B -> A) is rejected."""
        with pytest.raises(ValueError, match="Repeated banks create a routing loop"):
            SettlementRoute(
                route_id="loop-route",
                banks=(
                    RouteBank(bank_id="scotiabank", jurisdiction="CA"),
                    RouteBank(bank_id="jpmorgan_chase", jurisdiction="US"),
                    RouteBank(bank_id="scotiabank", jurisdiction="CA"),  # Loop!
                ),
            )

    @pytest.mark.asyncio
    async def test_multihop_indexer_block_ingestion_and_event_linking(self):
        """BlockchainIndexer indexes multi-hop V2 settlement blocks and links them."""
        blocks_coll = AsyncMock()
        txs_coll = AsyncMock()
        events_coll = AsyncMock()
        db = AsyncMock()
        db.chain_blocks = blocks_coll
        db.chain_transactions = txs_coll
        db.contract_events = events_coll

        blocks_coll.find_one.return_value = None  # No reorg

        indexer = BlockchainIndexer(db, tenant_id="chainlex-demo", chain_id=11155111)

        tx_hash = "0x" + "aa" * 32
        log = make_v2_log(
            settlement_id="0x" + "01" * 32,
            initiator="0x1111111111111111111111111111111111111111",
            beneficiary="0x2222222222222222222222222222222222222222",
            tx_hash=tx_hash,
        )

        block = {
            "number": 500,
            "hash": "0x" + "bb" * 32,
            "parent_hash": "0x" + "cc" * 32,
            "timestamp": 1700000000,
        }
        transactions = [
            {"hash": tx_hash, "from": "0x1111", "to": "0x2222", "value_minor": 0, "status": 1}
        ]

        result = await indexer.ingest_block(block, transactions=transactions, logs=[log])
        assert result["block_number"] == 500
        assert result["tx_count"] == 1
        assert result["event_count"] == 1
        assert result["reorg_detected"] is False

        # Verify transaction update received the decoded settlements array
        tx_call = txs_coll.update_one.call_args[0]
        assert tx_call[0] == {"tenant_id": "chainlex-demo", "tx_hash": tx_hash}
        settlements = tx_call[1]["$set"]["settlements"]
        assert len(settlements) == 1
        assert settlements[0]["event_name"] == "SettlementInitiated"
        assert settlements[0]["route"]["route_id"] == "corridor-demo-route"
        assert len(settlements[0]["route"]["banks"]) == 3
