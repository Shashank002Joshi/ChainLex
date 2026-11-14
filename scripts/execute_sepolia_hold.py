"""Execute an auditable on-chain protective compliance hold on Ethereum Sepolia."""

import asyncio
import os
import sys
from uuid import uuid4

from chainlex.connectors.evm import EVMConnector
from chainlex.domain.models import HoldAction, ProbeOutcome


async def main():
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

    print("==================================================")
    print(" ChainLex Sepolia Protective Freeze Execution")
    print("==================================================")
    print(f"Contract: {contract_address}")
    print("Network: Ethereum Sepolia (ChainID: 11155111)")

    connector = EVMConnector(
        rpc_url=rpc_url,
        contract_address=contract_address,
        private_key=private_key,
        required_confirmations=1,
    )

    settlement_uuid = uuid4().hex
    settlement_id = f"0x{settlement_uuid}{settlement_uuid}"
    print(f"\n1. Flagged Settlement ID: {settlement_id}")
    print("   Violation: Cross-Border Wire missing FINTRAC Travel Rule evidence")
    print("   Action: Dispatched automated protective hold on SettlementHub")

    action = HoldAction(
        tenant_id="bank_a",
        settlement_id=settlement_id,
        amount_minor=25_000_000,  # $250,000.00
    )

    idempotency_key = f"idem-sepolia-{settlement_uuid[:12]}"
    prepared = await connector.prepare(action, idempotency_key=idempotency_key)
    print(f"2. Deterministic Operation ID: {prepared.operation_id}")

    print("3. Signing EIP-1559 transaction offline and broadcasting to Sepolia...")
    ref = await connector.dispatch(prepared)
    print(f"   Transaction Broadcast: {ref.tx_hash}")
    etherscan_tx_url = connector.get_explorer_url(ref.tx_hash)
    print(f"   Etherscan Tx URL: {etherscan_tx_url}")

    print("\n4. Probing on-chain receipt, event logs, and contract assertion...")
    for attempt in range(1, 30):
        probe = await connector.probe(prepared)
        if probe.outcome == ProbeOutcome.CONFIRMED:
            print("\n[SUCCESS] Confirmed in block!")
            print(f"Outcome: {probe.outcome}")
            print(f"State effect: {probe.effect}")
            print(f"Verified on contract: isSettlementHeld({settlement_id}) == True")
            print(f"\nEtherscan Verification Link:\n👉 {etherscan_tx_url}\n")
            await connector.close()
            return
        elif probe.outcome == ProbeOutcome.REVERTED:
            print("[REVERT] Transaction reverted!")
            sys.exit(1)
        else:
            print(f"   Attempt {attempt}: status={probe.outcome}... waiting for mining")
            await asyncio.sleep(4)

    print("Timeout waiting for Sepolia block confirmation")
    await connector.close()
    sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
