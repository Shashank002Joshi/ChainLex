"""ChainLex Dynamic End-to-End Compliance Verification CLI Runner.

CLI entrypoint to execute the complete 6-leg FSM compliance lifecycle for ANY dynamic transaction:
  Leg 1: Intake & Invariant Validation (Wash trades, Non-zero hashes, Routing loops)
  Leg 2: Identity & Route Admission Evaluation (Position-scoped Bank Allowlist checks)
  Leg 3: Evidence & Multi-Jurisdictional Discovery (FINTRAC, OFAC/FinCEN, MAS)
  Leg 4: Multi-Agent Compliance Court Deliberation (Prosecutor, Defense, CCO)
  Leg 5: Dispatch & Protective Hold Execution (EVMConnector on Sepolia or Simulator)
  Leg 6: State Pinning & Merkle Audit Anchoring (Canonical SHA-256 + Merkle root)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from chainlex.services.e2e_runner import run_e2e_verification


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ChainLex Dynamic End-to-End Compliance Verification Runner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--scenario",
        choices=["cross_country", "binance_hack", "multihop_routing", "custom"],
        default="custom",
        help="Select a scenario preset or custom parameterization",
    )
    parser.add_argument(
        "--origin-bank",
        default="scotiabank",
        help="Originating bank identifier",
    )
    parser.add_argument(
        "--origin-country",
        default="CA",
        help="Originating bank jurisdiction (ISO-2)",
    )
    parser.add_argument(
        "--inter-bank",
        action="append",
        dest="inter_banks",
        help="Intermediary bank identifier (can be specified multiple times)",
    )
    parser.add_argument(
        "--inter-country",
        action="append",
        dest="inter_countries",
        help="Intermediary bank jurisdiction (can be specified multiple times)",
    )
    parser.add_argument(
        "--dest-bank",
        default="dbs",
        help="Destination bank identifier",
    )
    parser.add_argument(
        "--dest-country",
        default="SG",
        help="Destination bank jurisdiction (ISO-2)",
    )
    parser.add_argument(
        "--amount",
        type=float,
        default=250000.0,
        help="Settlement asset amount",
    )
    parser.add_argument(
        "--symbol",
        default="USDC",
        help="Asset symbol",
    )
    parser.add_argument(
        "--decimals",
        type=int,
        default=6,
        help="Asset decimals",
    )
    parser.add_argument(
        "--initiator",
        default="0x1111111111111111111111111111111111111111",
        help="Initiator wallet address",
    )
    parser.add_argument(
        "--beneficiary",
        default="0x2222222222222222222222222222222222222222",
        help="Beneficiary wallet address",
    )
    parser.add_argument(
        "--instructions-hash",
        default=None,
        help="Off-chain Travel Rule commitment hash (32-byte hex)",
    )
    parser.add_argument(
        "--no-cdd",
        action="store_false",
        dest="cdd_complete",
        default=True,
        help="Simulate incomplete Customer Due Diligence",
    )
    parser.add_argument(
        "--no-travel-rule",
        action="store_false",
        dest="travel_rule_complete",
        default=True,
        help="Simulate incomplete Travel Rule compliance",
    )
    parser.add_argument(
        "--no-sanctions-clear",
        action="store_false",
        dest="sanctions_clear",
        default=True,
        help="Simulate sanctions hit",
    )
    parser.add_argument(
        "--no-beneficial-ownership",
        action="store_false",
        dest="beneficial_ownership_checked",
        default=True,
        help="Simulate unverified beneficial ownership (omnibus commingling)",
    )
    parser.add_argument(
        "--wash-trade",
        action="store_true",
        default=False,
        help="Simulate wash trade (initiator == beneficiary)",
    )
    parser.add_argument(
        "--zero-instructions-hash",
        action="store_true",
        default=False,
        help="Simulate zeroed-out instructions hash (loophole test)",
    )
    parser.add_argument(
        "--rogue-sender",
        action="store_true",
        default=False,
        help="Simulate unlisted rogue hot wallet attempting internal sweep",
    )
    parser.add_argument(
        "--strict-intermediary",
        action="store_true",
        default=False,
        help="Simulate intermediary bank enforcing ALL_ROUTE_POSITIONS allowlist",
    )
    parser.add_argument(
        "--tx-file",
        help="Path to JSON file containing settlement transaction parameters",
    )
    parser.add_argument(
        "--mode",
        choices=["simulated", "sepolia"],
        default="simulated",
        help="Execution target: simulated (mock EVM) or sepolia (public testnet)",
    )
    parser.add_argument(
        "--report-out",
        help="Save full structured JSON report to this file path",
    )
    return parser


def apply_scenario_defaults(args: argparse.Namespace) -> None:
    """Pre-configures scenario parameters if a preset is selected."""
    if args.scenario == "cross_country":
        args.origin_bank = "scotiabank"
        args.origin_country = "CA"
        args.inter_banks = ["jpmorgan_chase"]
        args.inter_countries = ["US"]
        args.dest_bank = "dbs"
        args.dest_country = "SG"
        args.amount = 250000.0
        args.travel_rule_complete = False

    elif args.scenario == "binance_hack":
        args.origin_bank = "scotiabank"
        args.origin_country = "CA"
        args.inter_banks = ["jpmorgan_chase"]
        args.inter_countries = ["US"]
        args.dest_bank = "dbs"
        args.dest_country = "SG"
        args.amount = 5000000.0
        args.beneficial_ownership_checked = False
        args.cdd_complete = True
        args.travel_rule_complete = True

    elif args.scenario == "multihop_routing":
        args.origin_bank = "scotiabank"
        args.origin_country = "CA"
        args.inter_banks = ["jpmorgan_chase"]
        args.inter_countries = ["US"]
        args.dest_bank = "dbs"
        args.dest_country = "SG"
        args.strict_intermediary = True


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.scenario != "custom":
        apply_scenario_defaults(args)

    if args.tx_file:
        file_path = Path(args.tx_file)
        if not file_path.exists():
            print(f"Error: Tx file not found: {args.tx_file}", file=sys.stderr)
            sys.exit(1)
        with file_path.open() as f:
            file_data = json.load(f)
            settlement_entry = file_data
            if "settlements" in file_data and file_data["settlements"]:
                settlement_entry = file_data["settlements"][0]

            if "initiator_wallet" in settlement_entry:
                args.initiator = settlement_entry["initiator_wallet"]
            if "beneficiary_wallet" in settlement_entry:
                args.beneficiary = settlement_entry["beneficiary_wallet"]
            if "asset" in settlement_entry:
                asset = settlement_entry["asset"]
                args.symbol = asset.get("symbol", args.symbol)
                args.decimals = asset.get("decimals", args.decimals)
                if "amount_atomic" in asset:
                    args.amount = float(asset["amount_atomic"]) / (10**args.decimals)
            if "route" in settlement_entry and "banks" in settlement_entry["route"]:
                banks = settlement_entry["route"]["banks"]
                if len(banks) >= 2:
                    args.origin_bank = banks[0]["bank_id"]
                    args.origin_country = banks[0]["jurisdiction"]
                    args.dest_bank = banks[-1]["bank_id"]
                    args.dest_country = banks[-1]["jurisdiction"]
                    if len(banks) > 2:
                        args.inter_banks = [b["bank_id"] for b in banks[1:-1]]
                        args.inter_countries = [b["jurisdiction"] for b in banks[1:-1]]
                    else:
                        args.inter_banks = []
                        args.inter_countries = []
            if "instructions_hash" in settlement_entry:
                args.instructions_hash = settlement_entry["instructions_hash"]

    report = asyncio.run(
        run_e2e_verification(
            scenario=args.scenario,
            origin_bank=args.origin_bank,
            origin_country=args.origin_country,
            inter_banks=args.inter_banks,
            inter_countries=args.inter_countries,
            dest_bank=args.dest_bank,
            dest_country=args.dest_country,
            amount=args.amount,
            symbol=args.symbol,
            decimals=args.decimals,
            initiator_address=args.initiator,
            beneficiary_address=args.beneficiary,
            instructions_hash=args.instructions_hash,
            cdd_complete=args.cdd_complete,
            travel_rule_complete=args.travel_rule_complete,
            sanctions_clear=args.sanctions_clear,
            beneficial_ownership_checked=args.beneficial_ownership_checked,
            wash_trade=args.wash_trade,
            zero_instructions_hash=args.zero_instructions_hash,
            rogue_sender=args.rogue_sender,
            strict_intermediary=args.strict_intermediary,
            mode=args.mode,
        )
    )

    if args.report_out:
        out_path = Path(args.report_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w") as f:
            json.dump(report, f, indent=2)
        print(f"Full JSON verification report saved to: {out_path}")


if __name__ == "__main__":
    main()
