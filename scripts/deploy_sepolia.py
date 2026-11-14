"""Deploy SettlementHub to Ethereum Sepolia testnet."""

import os
import sys
from pathlib import Path

from eth_account import Account
from web3 import Web3

from chainlex.blockchain.artifacts import SETTLEMENT_HUB_ABI

BIN_PATH = Path("contracts/SettlementHub.bin")
with open(BIN_PATH) as f:
    BYTECODE = f.read().strip()


def main():
    pk = os.environ.get(
        "CHAINLEX_SEPOLIA_PRIVATE_KEY",
        "adc69945ea839c9167392aa45eba5291d72141529be8310495e3688a28e2ca36",
    )
    if not pk.startswith("0x"):
        pk = "0x" + pk

    rpc_url = os.environ.get(
        "CHAINLEX_SEPOLIA_RPC_URL", "https://ethereum-sepolia-rpc.publicnode.com"
    )

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        print(f"Error: Unable to connect to Sepolia RPC at {rpc_url}")
        sys.exit(1)

    account = Account.from_key(pk)
    print(f"Deploying from address: {account.address}")

    balance = w3.eth.get_balance(account.address)
    print(f"Balance: {w3.from_wei(balance, 'ether')} ETH")
    if balance == 0:
        print("Error: Account has 0 balance on Sepolia!")
        sys.exit(1)

    contract = w3.eth.contract(abi=SETTLEMENT_HUB_ABI, bytecode=BYTECODE)
    nonce = w3.eth.get_transaction_count(account.address)
    chain_id = w3.eth.chain_id

    fee_history = w3.eth.fee_history(1, "latest", [25.0])
    base_fee = fee_history["baseFeePerGas"][-1]
    priority_fee = w3.to_wei(2, "gwei")
    max_fee = int(base_fee * 1.5) + priority_fee

    construct_tx = contract.constructor().build_transaction(
        {
            "from": account.address,
            "nonce": nonce,
            "chainId": chain_id,
            "maxFeePerGas": max_fee,
            "maxPriorityFeePerGas": priority_fee,
        }
    )

    signed_tx = w3.eth.account.sign_transaction(construct_tx, private_key=pk)
    print("Broadcasting deployment transaction to Sepolia...")
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"Deployment tx broadcast: https://sepolia.etherscan.io/tx/{tx_hash.hex()}")

    print("Waiting for block confirmation...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    contract_address = receipt.contractAddress
    print("\nSUCCESS! SettlementHub deployed to Sepolia:")
    print(f"Contract Address: {contract_address}")
    print(f"Block Number: {receipt.blockNumber}")
    print(f"Gas Used: {receipt.gasUsed}")
    print(f"Etherscan link: https://sepolia.etherscan.io/address/{contract_address}")


if __name__ == "__main__":
    main()
