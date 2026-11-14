# Country regulations and review policies

## Normal database seed

`uv run chainlex-db seed-demo` now includes the current 12 review policies and
three bank-admission policies, independently of regulation embeddings. Policies
are bound to `CHAINLEX_DEMO_TENANT_ID` and inserted inactive and UNVERIFIED.
Existing review decisions, allowlists, and versioned records are preserved.

With a configured Voyage key, the command also embeds and ingests the 12 source
summaries. Without a key, it reports the regulation phase as skipped and stores
no unembedded regulations. A provider failure is an error after policy seeding;
rerunning preserves those policies and retries only missing regulation versions.
All vectors in the batch validate before the first regulation write.

The wheel carries the same corpus, so the default seed is independent of the
current directory. Manual reset still restores only the original six entity and
four case fixtures and preserves all policy/regulation records.

## Explicit corpus validation and ingestion

Run from the repository root:

```sh
uv run python -m chainlex.services.country_cli validate
uv run python -m chainlex.services.country_cli ingest
```

Validation is offline. Ingestion calls Voyage and writes to MongoDB; it requires
`CHAINLEX_MONGODB_URI`, `CHAINLEX_DATABASE`, `CHAINLEX_DEMO_TENANT_ID` and
`CHAINLEX_VOYAGE_API_KEY` from `.env`. Bootstrap collections first with
`uv run chainlex-db bootstrap`. Atlas keys use the default endpoint. For Voyage
platform keys, set `CHAINLEX_EMBEDDING_ENDPOINT=https://api.voyageai.com/v1/embeddings`
in `.env`; this also applies to normal seeding. The explicit ingestion command's
`--endpoint` argument overrides that setting.

The corpus contains 12 source-linked summaries and 12 internal review policies:
four each for SG/MAS, CA/FINTRAC and US/OFAC/FinCEN. It is a starter dataset,
not comprehensive country coverage. SG uses the official notice overview rather
than claiming paragraph-level analysis of the notice PDF.
ISO alpha-2 country codes are used here; older fixtures use USA/SGP and must be
normalized by the caller. Country alone does not establish legal applicability:
the analyst must check entity type, activity, legal nexus and exceptions.

Summaries are UNVERIFIED and effective dates are deliberately unknown. An officer
must verify the current text, applicability and effective date before marking a
stored version VERIFIED and setting a BSON `valid_from`. Unknown `valid_until`
is open-ended, not proof a rule remains current. Reviewed rules are eligible only
with matching tenant/country, active status, valid dates and adequate clearance.
Create the Atlas `regulations_vector_idx` using `src/chainlex/db/vector_indexes.json`.

Ingestion stores immutable text-hash versions using `$setOnInsert`. Repeated runs
preserve officer edits. When changing a rule, explicitly retire the old version;
this CLI does not infer supersession or legal validity. Repeated ingestion skips
existing content versions with valid embeddings and preserves review changes.
An incompatible existing embedding requires explicit repair or migration.
The current HTTP client has a 30-second timeout and
surfaces provider errors; automatic retry/reranking are future work.

Policies are internal demo controls linked by `source_rule_ids`, not statutory
mandates to freeze assets. They are inserted inactive and UNVERIFIED. The pure
`evaluate_policies` function previews a supplied policy list and returns REVIEW
for missing/adverse facts, otherwise NO_MATCH (never approval). Production callers
must load only active, reviewed, tenant-scoped policies and verify source versions
before using a decision. No worker dispatch or API route is connected yet.

Use `CaseFacts.query_text()` to describe a transaction; `retrieve_rules` embeds
that query and executes Atlas retrieval. Tenant and clearance must come from
trusted server identity. Returned records retain source URL, section, text hash
and vector score for citations; similarity scores do not establish legal risk.

Flow: official source → reviewed regulation chunk → document embedding → Atlas;
case facts → query embedding → governed retrieval → analyst citations;
structured facts → deterministic policy preview → officer review.

## File responsibilities

- `data/country_rules/regulations.json`: summaries of external regulations and
  official guidance. Country, source, citation, applicability, topics and example
  queries provide context for embeddings and the agent.
- `data/country_rules/policies.json`: internal operational policies. Each policy
  links to regulations through `source_rule_ids` and uses structured facts to
  determine whether officer review is required. Outcomes are REVIEW or NO_MATCH;
  they do not automatically freeze assets or establish a legal violation.
- `docs/country-rules.md`: developer handoff and operating instructions. This
  document is not sent to Voyage or stored in MongoDB.

`example_query` is a sample sentence for retrieval testing, not a precomputed
query vector. `applicability_notes` describes scope; the implementation does not
automatically determine whether a company is subject to a regulation.
For `required_fact`, true means the control assessment has been completed using
evidence, including a supported determination that it does not apply. False means
the control is not satisfied; null means unknown. Both false and null trigger
REVIEW. The analysis layer must calculate amount thresholds and group related
transactions over 24 hours; embedding similarity cannot perform those checks.

## Embedding and MongoDB integration

`src/chainlex/services/embeddings.py` is the single shared async Voyage client for
transactions, regulations and queries. It owns the model/dimension constants,
response validation and embedding metadata. `TransactionVectorizer` now accepts
this client instead of a synchronous Voyage SDK client; calls must be awaited.
Both document workflows store content hashes and model/version metadata to avoid
re-embedding unchanged content. Concurrent imports can still make redundant
provider requests; no distributed embedding lock is implemented.

This branch implements regulation embedding in Python. The JSON files do not
contain precomputed vectors, and live Voyage/Atlas ingestion has not been run.
The flow is:

```text
regulations.json
 → Regulation.embedding_text(): combine country, title, topics, scope and rule
 → VoyageEmbeddings.embed(..., input_type="document")
 → Validate 1024 dimensions per vector
 → ingest_rules(): write to CHAINLEX_DATABASE.regulations

CaseFacts describing a case
 → query_text()
 → VoyageEmbeddings.embed(..., input_type="query")
 → retrieve_rules(): search regulations using regulations_vector_idx
 → Return rule text, source_url, section, text_hash and vector_score
```

Set these variables in `.env`. URL-encode special characters in the actual password:

```dotenv
CHAINLEX_MONGODB_URI=mongodb+srv://chainlex:ENCODED_PASSWORD@cluster0.6jb5nv.mongodb.net/?retryWrites=true&w=majority
CHAINLEX_DATABASE=chainlex
CHAINLEX_DEMO_TENANT_ID=chainlex-demo
CHAINLEX_VOYAGE_API_KEY=YOUR_KEY
```

To validate or ingest regulations without requiring a policies file:

```sh
uv run python -m chainlex.services.country_cli validate --regulations-only
uv run chainlex-db bootstrap
uv run python -m chainlex.services.country_cli ingest --regulations-only
```

Remove `--regulations-only` to ingest both datasets. The target collections are:

| Collection | Contents | Embedded? |
|---|---|---|
| `regulations` | Rule text, sources, governance fields, 1024-dimensional `embedding` | Yes |
| `policies` | Required fact, REVIEW outcome, source rule IDs, policy version | No |

Each regulation receives `tenant_id`, `schema_version: 1`, `clearance_level: 1`,
`embedding_model`, `embedding_version` and `text_hash`. Python datetime values
are stored as BSON Dates rather than JSON strings. Inspect the results in
`chainlex.regulations` using Compass.

Next, create `regulations_vector_idx` in Atlas using the `definition` from
`vector_indexes.json` with 1024 dimensions and cosine similarity. Wait until the
index is queryable. Successful ingestion does not make every record eligible for
retrieval: default UNVERIFIED records with unknown `valid_from` remain excluded
by the governance filters.

There is no automatic review, API endpoint or worker integration yet. Call
`retrieve_rules(db, voyage, case, tenant_id, clearance)` to integrate retrieval
with the agent. The summaries reference official sources, but effective dates
and legal applicability still require review for each record.

## Multi-bank routes and internal originator allowlists

A settlement route is an ordered list of banks, for example:

```json
{
  "route_id": "sg-us-ca-001",
  "banks": [
    {"bank_id": "dbs", "jurisdiction": "SG"},
    {"bank_id": "jpmorgan_chase", "jurisdiction": "US"},
    {"bank_id": "scotiabank", "jurisdiction": "CA"}
  ]
}
```

`SettlementRoute` accepts 2–32 distinct banks. The first is the originating bank,
the last is the destination, and all others are intermediaries. Routing loops
are rejected. `CaseFacts.route` includes this path in the embedding query.
`applicable_jurisdictions` combines explicit jurisdictions with every route bank's
country, so an intermediary's country cannot be omitted from retrieval or country
policy previews. This identifies candidate regulations, not definitive legal scope.
Route retrieval runs a query per country with up to three results each, rather
than letting one country's matches consume a global top-three budget. An empty
country result is not proof that no regulation applies.
Only SG, CA and US are currently supported. The routing engine supplies the chosen
path; this module does not calculate cheapest paths or execute individual legs.

`data/country_rules/bank_policies.json` contains three separate bank admission
fixtures. They are internal policies with no fabricated legal source IDs and are
stored in `policies` with `policy_type: BANK_ORIGINATOR_ALLOWLIST`. Standard CLI
validation/ingestion includes this optional file; `--regulations-only` excludes it.
Ingestion binds fixtures to the configured demo tenant and forces them inactive
and UNVERIFIED, regardless of input activation flags. Addresses are fictional.

The example bank IDs are `scotiabank` (Canada), `jpmorgan_chase` (United States)
and `dbs` (Singapore). `institutions.json` records display names, classifications
and official sources. Wealthsimple is a Canadian financial services platform,
not a bank; it is represented as an initiating institution rather than a routing
bank. See its [official explanation](https://www.wealthsimple.com/en-ca/magazine/how-safe-is-a-bank-account).
All wallet mappings, allowlists and routes are fictional demo configuration, not
these institutions' actual policies, partnerships or supported blockchain services.
`route_examples.json` contains validated examples in both corridor directions.
The catalog and route examples are offline fixtures, not yet loaded into a trusted
institution registry by the CLI. `CHAINLEX_DEMO_TENANT_ID=chainlex-demo` denotes
the consortium's demo namespace, not a bank in the route. Existing application
defaults still use the legacy tenant ID; set the environment variable consistently
when using the new examples.

Admission uses exact `(network, address)` membership, with normalized EVM address
case. An entry labelled Binance only passes for its explicitly approved wallet
on that network. A random EOA or the same address on another network is denied.
EOAs are not categorically forbidden: a bank can explicitly approve one.
Names, transaction memos and embedding similarity cannot grant admission.

By default `scope: ORIGINATING_BANK` checks the sender only when that bank is first
in the route. `ALL_ROUTE_POSITIONS` lets a bank require the original sender on its
own list even when acting as intermediary or destination. This does not check the
previous bank's wallet; that would require a separate counterparty policy.
Every route bank must have exactly one active VERIFIED policy in the caller's
tenant registry; missing/ambiguous configuration requires REVIEW. An empty active
originator allowlist denies all initiators. A reviewed originating-only policy at
an intermediate bank is explicitly marked NOT_APPLICABLE.

Agent integration:

```python
from chainlex.domain.routing import SettlementRoute, WalletIdentity
from chainlex.services.route_policy import load_bank_policies, evaluate_route_admission

# Supply these from the routing engine and verified sender authentication.
route = SettlementRoute.model_validate(selected_route)
sender = WalletIdentity.model_validate(authenticated_wallet)
policies = await load_bank_policies(db, route, principal.tenant_id)
admission = evaluate_route_admission(route, sender, principal.tenant_id, policies)
```

Sender authentication must verify control of the wallet (for example by signature
or trusted custody mapping). Request-provided wallet/name claims are insufficient.
The route must also come from a trusted routing engine/bank registry, not an
unvalidated client-selected bank list. Bank IDs are not tenant identities: visiting
a bank never grants access to that bank's private corpus. The current demo uses a
tenant-owned registry for the whole route; independent-bank authorization remains
a future integration.

Admission aggregates with DENY taking precedence over REVIEW, then PASS. PASS
means only these admission controls passed; the agent must still run regulatory
analysis, country policies and other approvals. Loaders retain policy IDs and
versions in results for auditing. No API/worker dispatch is connected yet; the
existing demo job endpoint still returns 501. Before dispatch, the future worker
must revalidate the selected route, sender and current policy versions to prevent
using a decision made before a route change or allowlist revocation.

## Event-to-workflow example and current integration gaps

Example: a fictional Wealthsimple-labelled wallet requests a settlement through
Scotiabank (CA), JPMorgan Chase (US) and DBS (SG).

1. A demo contract emits `SettlementInitiated(settlementId, from, to, amountMinor,
   currency)`. This event represents an initiation signal, not proof of final
   cross-border payment or proof the wallet belongs to a named institution.
2. `BlockchainIndexer` accepts supplied blocks/transactions/logs, decodes the
   event and writes tenant-scoped records to MongoDB. An actual RPC ingestion
   runner still needs to feed it blocks and logs.
3. `Web3EventBus` can watch inserted `contract_events` with Change Streams and
   invoke an injected callback. The application worker does not start this event
   bus or supply a compliance callback yet.
4. The future callback must resolve and authenticate wallet/institution identity,
   verify the settlement route and construct `CaseFacts`. Legacy events do not
   contain routing metadata. The additive V2 event now includes bank IDs, country
   codes, a route ID and intermediaries as unverified submitted claims; see
   [settlement events](./settlement-events.md) for the schema and migration steps.
5. `load_bank_policies` and `evaluate_route_admission` check the initiating wallet
   against the route's bank policies. A non-allowlisted wallet produces DENY;
   missing or inactive/unreviewed policies produce REVIEW.
6. `retrieve_rules` embeds a query for each route country using the shared Voyage
   client and searches the reviewed regulation corpus. Country policy previews
   assess structured facts; retrieved similarity scores cannot grant admission.
7. The future agent/worker must combine admission, regulatory findings and human
   approvals before dispatch. Subsequent execution, confirmation, audit logging
   and recovery still need to be wired into the workflow.

Steps 1–3 have separate contract/indexer/event-listener components. Steps 5–6 have
callable policy/retrieval services. The authenticated enrichment in step 4 and
the orchestration in step 7 remain integration work. The source event is already
on-chain; DENY prevents a subsequent settlement action, not the event's creation.
If unauthorized wallets must be unable to initiate the contract transaction at
all, a separate on-chain allowlist check must be added to `initiateSettlement`.
