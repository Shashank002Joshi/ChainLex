# Routed settlement events (V2)

The transaction envelope answers where and when a request appeared on-chain.
The settlement payload answers who submitted it, what asset amount it concerns,
and which institutional route was requested. Institution identities are distinct
from wallet addresses and from the tenant that can access the record.

## Recommended structure

| Field | Meaning and authority |
|---|---|
| `tenant_id` | Application-owned data access scope |
| `chain_id` | Chain identity supplied by the trusted RPC/indexer configuration |
| `tx_hash`, `block_hash`, `block_number`, `timestamp` | Transaction provenance |
| `status` | EVM execution result, not compliance approval or payment finality |
| `is_canonical`, `is_orphaned` | Indexer's fork tracking |
| `settlements[]` | One item per decoded V2 initiation log in this transaction |
| `settlements[].log_index`, `contract_address` | Exact source event within the transaction |
| `settlement_id` | Request identifier, separate from the transaction hash |
| `initiator_wallet` | V2 contract caller (`msg.sender`) |
| `beneficiary_wallet` | Intended beneficiary, separate from the transaction's `to` contract |
| `asset.amount_atomic` | Positive uint256 encoded as a decimal string for MongoDB/JSON |
| `asset.symbol`, `decimals`, `contract_address` | Submitted asset identity and scaling |
| `route.route_id`, `route.banks[]` | Ordered originating, intermediary and destination institutions |
| `route.banks[].bank_id`, `jurisdiction` | Stable registry ID and ISO alpha-2 country |
| `instructions_hash` | Commitment/reference to transfer instructions stored off-chain |
| `institution_verification` | UNVERIFIED until trusted identity and route checks are performed |

The first route institution is the originating bank, the last is the destination,
and all others are intermediaries. Countries are derived from the entire ordered
route rather than duplicated as potentially inconsistent source/destination fields.
`250000000` atomic units at 6 decimals means `250.000000 USDC`, not USD 2,500,000.
Do not use floating-point amounts or assume all assets have two decimals.

`data/country_rules/settlement_transaction_example.json` shows the indexed shape.
All institution relationships, wallet addresses, token contracts and hashes in
that example are fictional. Wealthsimple is the demo initiating institution;
Scotiabank, JPMorgan Chase and DBS are the routing banks. An on-chain symbol,
country or institution ID is a submitted claim; validate it against the trusted
asset/institution registry. The contract does not prove ownership or licensing.

## Contract and ABI

`initiateRoutedSettlement(bytes32 settlementId, address beneficiary,
SettlementDetails details)` emits `SettlementInitiatedV2`. The details tuple contains:

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

The two arrays must have identical lengths of 2–32 entries; repeated institution
IDs, unknown country codes (currently anything other than CA/US/SG), zero amounts
and decimals above 18 are rejected. V2 identifiers cannot be submitted twice.
The contract records the request and emits the event; it does not transfer tokens
or enforce bank allowlists. A relayer calling the contract is the indexed initiator;
representing an original signer would need a separately verified authorization.

The event's indexed fields are settlement ID, initiator and beneficiary. Private
names, account numbers, Travel Rule payloads and compliance evidence stay off-chain.
The bytes32 instructions hash commits to those instructions without embedding the
instructions themselves in a public log. Hash creation/storage is handled by the
calling application and is not implemented by this contract.

The Python ABI in `blockchain/artifacts.py` includes both event versions and the
new function. `domain/settlement.py` validates the decoded V2 structure. Invalid
V2 events are rejected rather than assigned a default USD amount or partial route.

## Indexing, retrieval and policy integration

```python
indexer = BlockchainIndexer(db, tenant_id="chainlex-demo", chain_id=11155111)
await indexer.ingest_block(block, transactions=transactions, logs=logs)
```

Provide normalized integer block numbers, timestamps and log indexes and the
corresponding transaction/receipt list. `chain_id` must come from the trusted node,
not user input. The current database keys assume one chain per tenant; configure
separate namespaces for other chains until chain-aware key migration is added.

The indexer stores the full payload under `contract_events.decoded_params` and
collects all V2 request logs under the matching `chain_transactions.settlements`.
Event-only ingestion stores event records; transaction summaries require the
matching transaction to be included in the ingestion call. The event name is
normalized to `SettlementInitiated` so the existing `Web3EventBus` callback handles
both versions; `source_event_name` and `event_version` retain the distinction.
Raw transaction `from`/`to` fields are retained independently of request participants.

Transaction narratives include exact amounts and the route, so the shared Voyage
document embedding now contains the banks and countries. A changed route changes
the content hash and invalidates the transaction embedding cache. To retrieve
regulations, use the decoded `route` in `CaseFacts`; every route country receives
its own query embedding and result budget. Bank admission checks still compare
the authenticated wallet's network/address against the exact allowlist.

Country metadata alone never proves jurisdictional applicability. The worker must
verify wallet ownership, institution/country assignments, route authorization and
asset metadata before policy decisions. An EVM receipt success means the event
was emitted, not that the settlement was approved or completed. The API/worker
orchestration is still scaffolded and is not automatically wired by this change.

## Migration and validation

Legacy `initiateSettlement` and its original event/topic remain available. Legacy
records have no inferred institutions, route or countries; they require enrichment
before country-specific automated processing. The V2 uniqueness mapping does not
retroactively deduplicate legacy IDs; applications must use distinct IDs/namespaces
across legacy and V2 submission paths.

An already deployed contract does not acquire the new function: deploy this
version and update the configured contract address/ABI to emit routed events.
No deployment is performed by these changes. Restrict the RPC event collector
to approved contract addresses; the decoder alone does not authenticate contracts.

```sh
uv run pytest
forge test --contracts contracts --match-contract SettlementHubTest
```

The Python tests check V2 decoding, malformed payload rejection, exact large
amounts, country retrieval, multiple requests per transaction and event callbacks.
Solidity tests cover request creation, duplicate IDs, route loops, route array
length mismatch and continued legacy submission support.
