# Compliance FSM

The scaffold defines one FSM per proposed settlement, with six legs. The catalog
is implemented; durable handlers and transition execution are not. Authenticated
`GET /api/fsms/definition` exposes the current states, events, guards, writes, and
recovery descriptions with `runtime_implemented: false` and `guards_evaluated: false`.

## State and persistence

- `ComplianceFSM.state` is canonical; the leg is derived. Shared waits retain a
  validated origin/resume checkpoint. Lease, fence, attempt, and timers are runtime metadata.
- Every instance/event is scoped by server-bound `tenant_id` and `fsm_id`.
  Creation accepts a scenario, idempotency key, and optional previous-FSM reference.
- Events carry an ID, actor/source, expected state/revision, timestamp, and artifact
  references. Callers cannot supply an arbitrary next state or impersonate an officer.
- A future transition transaction must deduplicate the event, check its guards,
  save immutable versioned artifacts, advance state/revision, and append the audit event.
  External calls happen outside that transaction.
- New records use `compliance_fsms`, `fsm_id`, and `tenant_controls`; `compliance_cases`
  stores historical precedents. Bootstrap never deletes old job records or indexes.

## Intake

| Current state | Event | Next state | Required output or guard |
|---|---|---|---|
| No instance | `REQUEST_ACCEPTED` | `RECEIVED` | Authenticated tenant, allowlisted scenario, unique request key; save original request/input digest. |
| `RECEIVED` | `START_INTAKE` | `VALIDATING_CONTEXT` | Original request exists; record attempt. |
| `VALIDATING_CONTEXT` | `CONTEXT_VALIDATED` | `RESOLVING_PARTIES` | Supported pending settlement, positive integer minor units, explicit currency; save normalized facts. |
| `RESOLVING_PARTIES` | `PARTIES_RESOLVED` | `RESOLVING_JURISDICTIONS` | Exact network/address matches; save party versions/provenance. |
| `RESOLVING_JURISDICTIONS` | `JURISDICTIONS_RESOLVED` | `CONTEXT_READY` | Supported jurisdiction facts; save context snapshot/digest. |

Invalid input enters `REJECTED`; missing or contradictory facts require input.
A wallet address alone cannot establish physical jurisdiction or licensing status.
Recovery resumes the unfinished intake operation using current source versions.

## Evidence

| Current state | Event | Next state | Required output or guard |
|---|---|---|---|
| `CONTEXT_READY` | `START_EVIDENCE` | `EMBEDDING_QUERY` | Save factual narrative, input digest, and model. |
| `EMBEDDING_QUERY` | `QUERY_EMBEDDED` | `SEARCHING_REGULATIONS` | Valid 1,024-dimensional vector and saved query reference. |
| `SEARCHING_REGULATIONS` | `REGULATION_CANDIDATES_SAVED` | `SEARCHING_PRECEDENTS` | Tenant/jurisdiction/clearance/review/date filters; save candidates and relevance scores. |
| `SEARCHING_PRECEDENTS` | `PRECEDENT_CANDIDATES_SAVED` | `RERANKING_EVIDENCE` | Eligible tenant precedents or an explicit empty result. |
| `RERANKING_EVIDENCE` | `EVIDENCE_RERANKED` | `VALIDATING_EVIDENCE` | Ranked clauses plus applicability/exception references. |
| `VALIDATING_EVIDENCE` | `EVIDENCE_VALIDATED` | `EVIDENCE_READY` | Recheck authoritative versions, scope, review, and effective dates; save evidence digest. |

Retry only the unfinished operation; a later search failure does not require a new
valid embedding. `CONTEXT_STALE` returns to intake; `EVIDENCE_STALE` returns to query
embedding when context remains valid. Revoke downstream approvals/intents before
any possible send. Insufficient evidence never implies a clean result.

## Analysis

| Current state | Event | Next state | Required output or guard |
|---|---|---|---|
| `EVIDENCE_READY` | `START_ANALYSIS` | `GENERATING_FINDING` | Current context/evidence; save model, prompt version, input manifest. |
| `GENERATING_FINDING` | `FINDING_RETURNED` | `VALIDATING_FINDING` | Save the provider result as an untrusted candidate. |
| `VALIDATING_FINDING` | `FINDING_VALIDATED` | `FINDING_READY` | Schema, citations, source versions, and claims validate; save finding/digest. |

A finding is `EVIDENCE_SUPPORTED_RISK` or `REVIEW_REQUIRED`. The latter cannot
qualify for automatic authorization. Invalid output gets bounded regeneration;
exhaustion requires correction. Restart during validation reuses the saved candidate.

## Authorization

| Current state | Event | Next state | Required output or guard |
|---|---|---|---|
| `FINDING_READY` | `START_POLICY_CHECK` | `EVALUATING_POLICY` | Validated finding; save immutable proposal/version/digest. |
| `EVALUATING_POLICY` | `POLICY_AUTHORIZED` | `AUTHORIZED` | Current tenant, target, authority, policy, evidence, and amount checks; atomically save authorization/outbox intent. |
| `EVALUATING_POLICY` | `HUMAN_APPROVAL_REQUIRED` | `AWAITING_APPROVAL` | Otherwise eligible action exceeds automatic limit; save blocking reason and proposal digest. |
| `AWAITING_APPROVAL` | `OFFICER_APPROVED` | `EVALUATING_POLICY` | Matching officer tenant and current proposal version/digest; save decision and reevaluate policy. |
| `AWAITING_APPROVAL` | `OFFICER_REJECTED` | `DENIED` | Save rejection and exact proposal version. |
| `EVALUATING_POLICY` | `POLICY_DENIED` | `DENIED` | Save deterministic hard-denial reasons. |

The planned automatic hold limit is USD 250,000. Larger eligible proposals need an
officer; approval cannot waive missing evidence, invalid authority, or another
tenant's target. Changed inputs invalidate old approval. Recovery reuses the
saved proposal and unique outbox intent. No external submission happens here.

## Dispatch

| Current state | Event | Next state | Required output or guard |
|---|---|---|---|
| `AUTHORIZED` | `START_PREPARATION` | `PREPARING_ACTION` | Authorization and unique pending outbox intent exist. |
| `PREPARING_ACTION` | `ACTION_PREPARATION_SUCCEEDED` | `ACTION_PREPARED` | Save exact authorized payload, operation ID, idempotency key, digest, and recovery data before any send. |
| `ACTION_PREPARED` | `SUBMISSION_PERMITTED` | `SUBMITTING` | Revalidate authority/evidence/policy, lease/fence, and unpaused tenant control revision; persist dispatch permit. |
| `SUBMITTING` | `CONNECTOR_ACCEPTED` | `SUBMITTED` | Save actual connector reference/response; acceptance is not completion. |
| `SUBMITTING` | `SUBMISSION_AMBIGUOUS` | `SUBMISSION_UNKNOWN` | Save uncertain outcome and prepared identity; do not create a replacement operation. |

The permit transaction must conditionally write the same tenant control revision
that pause/policy/invalidation updates increment. A pause before the permit blocks
submission; one after it may encounter a permitted send that requires reconciliation.
Recovery from any possibly submitted state probes the saved operation first.

## Verification and finalization

| Current state | Event | Next state | Required output or guard |
|---|---|---|---|
| `SUBMITTING`, `SUBMITTED`, or `SUBMISSION_UNKNOWN` | `START_RECONCILIATION` | `RECONCILING` | Saved prepared-operation checkpoint and probe identity. |
| `RECONCILING` | `PROBE_PENDING`, `PROBE_UNKNOWN`, or `PROBE_NOT_FOUND` | `AWAITING_EFFECT` | Save observation and next probe time; remain within deadline. |
| `AWAITING_EFFECT` | `PROBE_DUE` | `RECONCILING` | Timer due and current worker lease. |
| `RECONCILING` | `PROBE_CONFIRMED` | `VERIFYING_EFFECT` | Save successful receipt; validate intended target/action/effect. |
| `VERIFYING_EFFECT` | `EFFECT_VERIFIED` | `EFFECT_CONFIRMED` | Receipt succeeds and the correct settlement is held; save verification evidence/digest. |
| `EFFECT_CONFIRMED` | `START_FINALIZATION` | `FINALIZING` | Verified-effect checkpoint; prepare final records. |
| `FINALIZING` | `FINAL_RECORD_COMMITTED` | `FINALIZED` | Atomically save final audit, one historical case, and terminal state. |

`NOT_FOUND` alone cannot authorize resubmission. Only authoritative absence and
renewed dispatch guards permit the identical prepared operation to return to
`ACTION_PREPARED`. Unresolved outcomes enter `MANUAL_REVIEW`; confirmed rejection
and absent hold enter `ACTION_FAILED`. Never start a replacement action while a
prior external outcome remains unknown.

Unavailable effect reads retry through the probe timer. A receipt/effect mismatch
requires review. Confirmed finalization recovery retries local writes only;
`FINALIZATION_RETRY_REQUESTED` cannot return to dispatch or network reconciliation.
Reporting failure never releases a protective hold. A completed historical case
is not automatically a reviewed precedent.

## Waits and terminal states

- `RETRY_WAIT`: persist safe origin, input digest/revision, consumed attempt, and
  due time. Resume that computation; invalid finding validation regenerates the candidate.
- `AWAITING_INPUT`: authorized correction creates a new revision and resumes the
  earliest affected prior state, never an arbitrary later state or submission.
- `MANUAL_REVIEW`: the saved checkpoint chooses reconciliation or local finalization.
- Defaults: three attempts, waits of two/four seconds, provider Retry-After capped
  at 60 seconds; probe every second for 120 seconds before manual review.
- Lease/heartbeat defaults are ten/three seconds; renewal must run independently
  of provider calls. Pause is orthogonal and permits read-only reconciliation.
- `REJECTED`, `DENIED`, `ACTION_FAILED`, and `FINALIZED` have no automatic exits.
  A deliberate new evaluation uses a new request key and links its predecessor.

## Submission-response-loss trace

```text
REQUEST_ACCEPTED            -> RECEIVED
START_INTAKE                -> VALIDATING_CONTEXT
CONTEXT_VALIDATED           -> RESOLVING_PARTIES
PARTIES_RESOLVED            -> RESOLVING_JURISDICTIONS
JURISDICTIONS_RESOLVED      -> CONTEXT_READY
START_EVIDENCE              -> EMBEDDING_QUERY
QUERY_EMBEDDED              -> SEARCHING_REGULATIONS
REGULATION_CANDIDATES_SAVED -> SEARCHING_PRECEDENTS
PRECEDENT_CANDIDATES_SAVED  -> RERANKING_EVIDENCE
EVIDENCE_RERANKED           -> VALIDATING_EVIDENCE
EVIDENCE_VALIDATED          -> EVIDENCE_READY
START_ANALYSIS              -> GENERATING_FINDING
FINDING_RETURNED            -> VALIDATING_FINDING
FINDING_VALIDATED           -> FINDING_READY
START_POLICY_CHECK          -> EVALUATING_POLICY
POLICY_AUTHORIZED           -> AUTHORIZED
START_PREPARATION           -> PREPARING_ACTION
ACTION_PREPARATION_SUCCEEDED -> ACTION_PREPARED
SUBMISSION_PERMITTED        -> SUBMITTING
SUBMISSION_AMBIGUOUS        -> SUBMISSION_UNKNOWN
START_RECONCILIATION        -> RECONCILING
PROBE_CONFIRMED             -> VERIFYING_EFFECT
EFFECT_VERIFIED             -> EFFECT_CONFIRMED
START_FINALIZATION          -> FINALIZING
FINAL_RECORD_COMMITTED      -> FINALIZED
```

The trace is the declared recovery contract, not an implemented crash-recovery
runtime. See `./src/chainlex/domain/` for definitions and `./tests/test_fsm.py`
for catalog/checkpoint tests.
