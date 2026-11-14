# Regulation and policy seed update

The user approved: **require Voyage embeddings before storing regulations; seed policies independently**.

## Behavior

- Ordinary `chainlex-db seed-demo` retains the six entity and four case fixtures and adds the current repository's 12 review policies plus three bank-admission policies for the configured demo tenant.
- New policies are inactive and UNVERIFIED. Tenant-scoped policy ID/version keys use additive insertion, preserving existing review decisions, allowlists, edits, and unrelated records.
- Regulations are inserted only through the existing real Voyage ingestion path, using `voyage-finance-2` and validated 1,024-dimensional vectors. No pending, placeholder, random, or zero vectors are written.
- Without a Voyage key, fixtures and policies still seed successfully. The JSON result explicitly reports the 12 available regulations as skipped, with the missing-key reason and zero regulation writes.
- With a configured key, seed policies first, then request embeddings for missing regulation content versions. Valid existing embeddings and reviewed records are reused. A provider/validation failure must not erase seeded policies or create unembedded regulation documents.
- Source content means the current checked-in corpus, not newly verified legislation. Seeding never promotes source summaries to legally verified status.

## Implementation boundaries

- Share corpus loaders between the existing country CLI and the new seed orchestration. Bundle the corpus in the wheel so normal seed commands work outside the source working directory.
- Reuse the current hash-versioned regulation ingestion and policy schema/IDs; validate the whole embedding batch before any regulation write.
- Keep manual reset unchanged: restore only the ten original fixture records and preserve regulations/policies.
- Run the updated normal seed against `chainlex_dev`, verify counts and existing-record preservation, and record what was skipped. Do not run a reset or live schema migration.

## Verification

Test policy-only success without a key, provider failure after independent policy insertion, malformed vectors with zero regulation writes, tenant isolation, repeat seeding with preserved review changes, source-version reuse, corpus loading from another working directory, and packaged corpus availability. Use a disposable Atlas database for integration checks before the configured database seed.
