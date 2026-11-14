"""Initiate a multi-hop routed settlement request on Ethereum Sepolia."""

import os
import sys
from uuid import uuid4

from eth_account import Account
from eth_utils import to_checksum_address
from web3 import Web3

from chainlex.blockchain.artifacts import SETTLEMENT_HUB_ABI


def main():
    rpc_url = os.environ.get(
        "CHAINLEX_SEPOLIA_RPC_URL", "https://ethereum-sepolia-rpc.publicnode.com"
    )
    private_key = os.environ.get(
        "CHAINLEX_SEPOLIA_PRIVATE_KEY",
        "adc69945ea839c9167392aa45eba5291d72141529be8310495e3688a28e2ca36",
    )
    contract_address = os.environ.get(
        "CHAINLEX_SEPOLIA_CONTRACT_ADDRESS", "0xABD45d376b0aA6dB71518b719D5f7E1e168cC4FB"
    )

    if not private_key.startswith("0x"):
        private_key = "0x" + private_key

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    account = Account.from_key(private_key)
    contract = w3.eth.contract(
        address=to_checksum_address(contract_address), abi=SETTLEMENT_HUB_ABI
    )

    settlement_uuid = uuid4().hex
    settlement_id = bytes.fromhex(f"{settlement_uuid}{settlement_uuid}")
    beneficiary = to_checksum_address("0x2222222222222222222222222222222222222222")

    details = (
        250_000_000_000,  # 250,000.00 USDC
        "USDC",
        6,
        to_checksum_address("0x3333333333333333333333333333333333333333"),
        "scotiabank-jpmorgan-dbs-demo",
        ["scotiabank", "jpmorgan_chase", "dbs"],
        ["CA", "US", "SG"],
        bytes.fromhex("44" * 32),
    )

    print("==================================================")
    print(" ChainLex Sepolia Routed Settlement Initiation")
    print("==================================================")
    print(f"Contract: {contract_address}")
    print(f"Settlement ID: 0x{settlement_id.hex()}")
    print("Corridor: Scotiabank (CA) -> JPMorgan Chase (US) -> DBS (SG)")
    print("Amount: 250,000.00 USDC (6 decimals)")

    nonce = w3.eth.get_transaction_count(account.address, "pending")
    chain_id = w3.eth.chain_id
    gas_price = w3.eth.gas_price

    tx = contract.functions.initiateRoutedSettlement(
        settlement_id, beneficiary, details
    ).build_transaction(
        {
            "from": account.address,
            "nonce": nonce,
            "chainId": chain_id,
            "gas": 400000,
            "gasPrice": int(gas_price * 1.3),
        }
    )

    signed = w3.eth.account.sign_transaction(tx, private_key=private_key)
    print("Broadcasting transaction to Sepolia...")
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    etherscan_url = f"https://sepolia.etherscan.io/tx/{tx_hash.hex()}"
    print(f"Broadcast: {tx_hash.hex()}")
    print(f"Etherscan link: {etherscan_url}")

    print("Waiting for block confirmation...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    if receipt.status == 1:
        print("\n[SUCCESS] Routed settlement initiated on-chain!")
        print(f"Block Number: {receipt.blockNumber}")
        print(f"Gas Used: {receipt.gasUsed}")
        print(f"View on Etherscan:\n👉 {etherscan_url}")
    else:
        print("[REVERT] Transaction failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
