# Country rules and bank policies

The corpus under `./data/country_rules/` contains 12 source-linked regulation
summaries, 12 internal review policies, and three bank-admission policies covering
SG, CA, and US. These are starter/demo records, not comprehensive legal coverage.

## Seed and ingestion

Run from `./`:

```sh
uv run chainlex-db bootstrap
uv run chainlex-db seed-demo
```

Policies seed independently, bound to `CHAINLEX_DEMO_TENANT_ID`, inactive and
UNVERIFIED. Regulations are stored only after real `voyage-finance-2` embeddings
validate at 1,024 dimensions. A missing key skips regulations explicitly; a provider
failure leaves independently seeded policies intact and reports an error.

```sh
uv run python -m chainlex.services.country_cli validate
uv run python -m chainlex.services.country_cli ingest --regulations-only
```

Validation is offline. Explicit ingestion requires `CHAINLEX_MONGODB_URI`,
`CHAINLEX_DATABASE`, `CHAINLEX_DEMO_TENANT_ID`, and `CHAINLEX_VOYAGE_API_KEY`.
`CHAINLEX_EMBEDDING_ENDPOINT` selects Atlas (`https://ai.mongodb.com/v1/embeddings`)
or Voyage (`https://api.voyageai.com/v1/embeddings`); `--endpoint` overrides it.

Repeated writes preserve existing records and officer decisions. Regulation text
uses content-hash versions; changed policies need an explicit version increment.
Old rules are not automatically retired. Corrupt/incompatible stored embeddings
require explicit repair. Seed data is bundled in the wheel.

## Data and retrieval

| Collection | Contents |
|---|---|
| `regulations` | Source URL, section, text, applicability, dates, review state, content hash, model/version, and real embedding |
| `policies` | Internal required-fact controls or bank originator allowlists, with tenant and explicit version |

Source summaries start UNVERIFIED with unknown effective dates. An officer must
verify applicability and set a BSON `valid_from`; `valid_until: null` is open-ended.
Governed retrieval requires matching tenant, country, review status, active state,
valid dates, and clearance. Relevance scores are not legal-risk probabilities.
Create `regulations_vector_idx` using `./src/chainlex/db/vector_indexes.json`.

`CaseFacts.query_text()` supplies factual query context. Documents use Voyage's
`document` input type; retrieval queries use `query`. Route retrieval reserves
results for each country, including intermediaries. ISO alpha-2 codes are used;
older USA/SGP entity fixtures need normalization.

## Policy semantics

`evaluate_policies` returns REVIEW for missing or adverse required facts and
NO_MATCH otherwise; it never grants approval. A true control flag requires evidence,
including a supported determination that a control does not apply. Amount thresholds
and related-transfer aggregation require structured calculations, not embeddings.

`evaluate_route_admission` checks a trusted route and authenticated originator's
exact network/address. DENY overrides REVIEW, which overrides PASS. Missing or
ambiguous reviewed bank policy requires review. ORIGINATING_BANK controls apply
at the first bank; ALL_ROUTE_POSITIONS can check the originator at every bank.
PASS covers admission only, not regulatory clearance.

Bank IDs do not grant access to another tenant's private corpus. Demo wallet
addresses and institution relationships are fictional. The application must verify
wallet control, route ownership, asset metadata, and country applicability before
using a policy decision. Before dispatch it must revalidate policy/route versions.

The callable retrieval/policy services and blockchain components are not yet wired
into the idle FSM worker. A recorded initiation event is not a completed payment.
