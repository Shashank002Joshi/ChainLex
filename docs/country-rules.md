# Country regulations and review policies

Run from the repository root:

```sh
uv run python -m chainlex.services.country_cli validate
uv run python -m chainlex.services.country_cli ingest
```

Validation is offline. Ingestion calls Voyage and writes to MongoDB; it requires
`CHAINLEX_MONGODB_URI`, `CHAINLEX_DATABASE`, `CHAINLEX_DEMO_TENANT_ID` and
`CHAINLEX_VOYAGE_API_KEY` from `.env`. Bootstrap collections first with
`uv run chainlex-db bootstrap`. Atlas keys use the default endpoint; legacy Voyage
keys require `--endpoint https://api.voyageai.com/v1/embeddings`.

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
this CLI does not infer supersession or legal validity. Repeated ingestion still
calls the embedding API. The current HTTP client has a 30-second timeout and
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
CHAINLEX_DEMO_TENANT_ID=bank_a
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
