# Settlement events

`SettlementInitiatedV2` records a routed request. It does not move tokens, prove
institution ownership, authorize settlement, or establish payment finality.
The implementation is in `./contracts/SettlementHub.sol`,
`./src/chainlex/blockchain/artifacts.py`, and `./src/chainlex/domain/settlement.py`.

## Payload

`initiateRoutedSettlement(bytes32 settlementId, address beneficiary,
SettlementDetails details)` takes:

```text
uint256 amountAtomic
string assetSymbol
uint8 assetDecimals
address assetContract
string routeId
string[] institutionIds
string[] countryCodes
bytes32 instructionsHash
```

The event indexes settlement ID, initiator (`msg.sender`), and beneficiary.
The ordered institution arrays describe the origin, intermediaries, and destination.
Example indexed data is in `./data/country_rules/settlement_transaction_example.json`;
its wallets, hashes, asset contracts, and institution relationships are fictional.

| Field | Meaning |
|---|---|
| `tenant_id` | Server-owned data access scope |
| `chain_id` | Trusted node/indexer configuration |
| `tx_hash`, `block_hash`, `block_number`, `timestamp` | Transaction provenance |
| `status` | EVM execution result, not compliance approval |
| `is_canonical`, `is_orphaned` | Fork tracking |
| `settlements[].log_index`, `contract_address` | Exact source event |
| `settlement_id` | Request ID, distinct from transaction hash |
| `initiator_wallet`, `beneficiary_wallet` | Submitted participants, distinct from transaction target contract |
| `asset.amount_atomic`, `symbol`, `decimals`, `contract_address` | Exact amount as a decimal integer string and submitted asset metadata |
| `route.route_id`, `route.banks[]` | Ordered institution IDs and ISO alpha-2 countries |
| `instructions_hash` | Commitment/reference to private instructions kept off-chain |
| `institution_verification` | UNVERIFIED until trusted identity/route checks pass |

`250000000` atomic units with six decimals means `250.000000` units. Preserve exact
integers; never assume two decimals or use floating point for settlement amounts.
Private names, account numbers, and Travel Rule payloads stay off-chain.

## Validation and authority

V2 rejects zero IDs, duplicate V2 IDs, missing/self beneficiary, missing instructions
hash, zero amounts, decimals above 18, invalid asset symbols, empty/oversized route
IDs, invalid institution IDs, repeated institutions, mismatched route arrays,
routes outside 2–32 institutions, and countries outside CA/US/SG.

Wallet control, institution ownership, token metadata, country applicability, and
bank allowlists require trusted off-chain checks. Initiation is not gated by those
allowlists. Freeze and audit-pinning actions require the contract operator.
A relayer is the recorded initiator unless original-signer authority is separately
verified. Restrict event collection to approved contract addresses.

## Indexing and retrieval

`BlockchainIndexer.ingest_block` accepts supplied blocks, transactions, and logs.
Use normalized integer heights/timestamps/log indexes and chain identity from the
trusted node. The current keys assume one chain per tenant; use separate namespaces
until chain-aware key migration is implemented.

Full event payloads are stored under `contract_events.decoded_params`. Matching
transactions collect V2 logs under `chain_transactions.settlements`; event-only
input does not fabricate a transaction summary. Raw transaction sender/target remain
independent. Normalized event names support the shared listener, while source event
name/version retain provenance.

Transaction narratives include the exact amount and route. Changed content invalidates
the embedding cache. `CaseFacts` retrieves rules for every route country; bank policies
check the authenticated originator's exact network/address. These standalone services
and the event bus are not automatically connected to the idle FSM worker.

Legacy events remain supported without inferred route/identity data. V2 uniqueness
does not retroactively deduplicate legacy IDs. Existing deployments need the new
contract and configured ABI/address before they can emit V2 events.

```sh
uv run pytest tests/test_routed_settlement.py tests/test_compliance_cases.py
forge test --contracts contracts --match-contract SettlementHubTest
```
