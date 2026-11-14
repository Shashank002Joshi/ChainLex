# Corpus Seeding Implementation Plan

> Execute inline using the approved [seed design](../specs/2026-11-14-corpus-seed-design.md). No additional design choice is pending.

**Goal:** Seed current policies independently and require real valid embeddings for regulation insertion.

**Architecture:** Shared corpus loading and policy insertion feed the normal database seed command. Existing fixture/reset helpers remain narrow. Regulation embedding is optional only when the credential is absent, with an explicit skipped result; configured-provider errors remain errors.

**Tech stack:** Existing Python, PyMongo, HTTPX, Voyage transport, pytest, and Hatch packaging.

## Tasks

- [x] Add failing tests for policy-only seeding, malformed embeddings, provider failure, preserved reviews, tenant keys, and source data loading independent of the working directory.
- [x] Extract corpus validation into `services/country_corpus.py` and reuse it from the country CLI.
- [x] Share additive policy ingestion in `services/country_rules.py`; validate regulation batches before writes and return insertion/reuse counts.
- [x] Add `db/corpus_seeding.py`, wire normal `seed-demo` to it, and retain the reset path's original fixture-only semantics.
- [x] Bundle `data/country_rules` through Hatch and include source data in the Docker build context.
- [x] Update seed/country documentation and error messages to explain missing credentials, inactive policies, and real embeddings.
- [x] Run offline tests, disposable Atlas integration, lint/format checks, build, and isolated-wheel seed-data loading.
- [x] Seed the configured database additively, compare preexisting records, and record resulting policy/regulation counts.

Verification commands:

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv build
uv run chainlex-db seed-demo
```

The last command writes fixtures/policies and embeds missing regulations only when a Voyage key is configured. Run without reset flags.
