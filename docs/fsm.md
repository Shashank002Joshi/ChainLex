# Compliance FSM: design and recovery

The implemented audit profile uses one durable FSM for intake, evidence,
analysis, draft publication, human review, and finalization. The separate
settlement profile below specifies authorization, dispatch and effect verification;
its instance handlers remain scaffolded.

## Implemented audit profile

Three agents map directly to the hackathon statements: Auditable Action enforces
identity/policy and assesses routes; Governed Memory retrieves tenant-scoped,
reviewed, unexpired precedents; Durable Completion coordinates saved steps and
verifies published artifacts. Human analyst/officer permissions are separate.

| State | Event and guard | Persisted result / recovery |
|---|---|---|
| `RECEIVED` | `CONTEXT_VALIDATED`: permitted adapter, valid route endpoints and bank sequence | Context and adapter snapshot; unsupported schema enters manual review |
| `RETRIEVING_EVIDENCE` | `QUERY_EMBEDDED`: permitted real Voyage request; `EVIDENCE_SAVED`: permitted search and authoritative governance checks | Saved vector, source/memory versions and retrieval status; a search retry reuses the vector |
| `ASSESSING_ROUTES` | `ANALYSIS_VALIDATED`: current policy and evidence | Per-bank/jurisdiction checks, conditional/no-route outcome, memory ablation, human gates and analysis digest |
| `PUBLISHING_DRAFT` | `REPORT_PREPARED`, then `DRAFT_REPORT_VERIFIED`: authorized publication, saved operation identity, read-back digest verification | Immutable snapshot/PDF manifest; after lost response probe the saved file before any new upload |
| `AWAITING_HUMAN_REVIEW` | `HUMAN_GATE_DECIDED`: officer, exact revision/digest, current dependencies | Recorded decisions; final sign-off requires all preceding gates resolved |
| `PUBLISHING_FINAL` | `FINAL_REPORT_VERIFIED`: dependencies/decisions remain valid and stored bytes match the snapshot manifest | Reviewed final PDF and `FINALIZED`; rejection remains an explicit outcome |

`RETRY_WAIT` stores its original business resume state, attempts and due time.
Transient failures use bounded retries and honor provider `Retry-After` up to
60 seconds. Exhaustion enters `MANUAL_REVIEW`; officer retry cannot install an
unknown schema adapter or jump to a later leg. Supported source versions 1/2 use
explicit adapters; the demo's version 99 stops for correction.

Each checkpoint commit atomically appends a hash-linked event and an immutable
`audit_artifacts` snapshot. Refreshing stale evidence clears working approvals,
but retains prior artifacts and PDFs. Policy proposals are input/version-bound
and cannot change active policy without a separate officer decision.

Fenced leases and independent heartbeats prevent stale workers from writing.
Action permits conditionally write both tenant control and active agent identity
inside the transaction, serializing with pause/revocation. Pause prevents new
permits; saved uploads are still probed and their outcomes recorded. A superseded
upload cannot become the current final report. Change Streams accelerate notice;
authoritative checks and polling remain the correctness path.

Use `/api/audits/definition`, `/api/audits/{id}`, its `/events`, `/reports`, and
`/export` endpoints. Export includes the complete ledger, policy snapshot,
immutable checkpoint artifacts and verified report manifests. Scripted source
references remain unverified and do not establish bank connectivity or legal
clearance. No audit transition submits a settlement action.

## Separate settlement profile

See the [architecture and demo plan](../chainlex_enriched_hackathon_plan.md) for presentation context and the [README](../README.md) for current capabilities.

## 1. State ownership and persistence

- One FSM instance evaluates one proposed settlement within one tenant. Its stable identity is `fsm_id`; all lookups include the authenticated `tenant_id`.
- One canonical `state` determines the current leg. Leg names, progress, and overall status are derived; six separate child FSMs or independently writable progress flags are not introduced.
- Worker identity, lease expiry, fencing token, attempt count, and next-attempt time are runtime metadata. A worker restart is not a business-state transition.
- Completed leg artifacts are immutable snapshots identified by version and digest. Advancing a leg requires its persisted output, not an in-memory return value.
- Use `ComplianceFSM`, `ComplianceState`, `ComplianceEvent`, and `ComplianceFSMRepository` in the proposed scaffold contracts. Store new instances in `compliance_fsms`; preserve `compliance_cases` for historical precedent memory.
- Public route contracts are `/api/fsms`, `/api/fsms/{fsm_id}`, `/api/fsms/{fsm_id}/events`, and `/api/fsms/{fsm_id}/export`. Proposal, memory, and tenant-control routes retain their existing purposes.
- The scaffold also exposes authenticated `GET /api/fsms/definition` for the static six-leg state/event catalog. Its output explicitly reports that runtime handlers are absent and guards have not been evaluated. Listed candidate events describe graph edges, not permission to execute them.
- Rename proposal/audit workflow references from `job_id` to `fsm_id`. Updating local bootstrap definitions does not authorize deleting or migrating an existing Atlas collection. The scaffold has no implemented job creation flow to migrate automatically.

### Transition envelope

Every transition specifies `from_state`, `event_type`, `to_state`, guards, durable writes, external work, retry behavior, and recovery behavior.

An event carries a unique `event_id`, `fsm_id`, `tenant_id`, source, expected FSM revision, timestamp, and references to its persisted result. Actor identity is assigned by the server. Model output cannot choose a next state, fabricate an approval event, or supply another tenant's identity.

The transition transaction:

1. Deduplicates the event using a unique `(tenant_id, fsm_id, event_id)` key.
2. Checks the expected state, revision, snapshot versions, worker lease, and fencing token. Operator-originated events use their role, proposal revision, and event guards; they do not impersonate a worker lease.
3. Saves the result artifact, increments the FSM revision, advances state, and appends the ordered audit event atomically.
4. Commits before the next handler performs external work. Network calls never execute inside the database transaction.

`START_*` events are generated by the deterministic worker when a ready checkpoint is due. The public API accepts a scenario and request idempotency key; it does not accept arbitrary state-transition commands.

## 2. Leg 1: Intake

Purpose: establish exactly which settlement, parties, and jurisdiction facts the FSM will evaluate. No regulatory conclusion is made here.

| Current state | Event | Next state | Guard and durable output |
|---|---|---|---|
| No instance | `REQUEST_ACCEPTED` | `RECEIVED` | Authenticated tenant, allowlisted scenario, stable settlement ID, and tenant-scoped request key; save original request and input digest. |
| `RECEIVED` | `START_INTAKE` | `VALIDATING_CONTEXT` | Request snapshot exists; record validation attempt. |
| `VALIDATING_CONTEXT` | `CONTEXT_VALIDATED` | `RESOLVING_PARTIES` | Amount is positive integer minor units, currency is explicit, target is supported, and settlement is pending; save normalized transaction facts. |
| `RESOLVING_PARTIES` | `PARTIES_RESOLVED` | `RESOLVING_JURISDICTIONS` | Resolve exact network/address records within the allowed scope; save party IDs, record versions, and provenance. |
| `RESOLVING_JURISDICTIONS` | `JURISDICTIONS_RESOLVED` | `CONTEXT_READY` | Required jurisdiction facts are supported; save the complete context snapshot and digest. |

Invalid syntax, unsupported actions, or a completed settlement emit `INTAKE_REJECTED` and enter terminal `REJECTED`. Unknown parties, unknown jurisdiction, or contradictory metadata emit `INPUT_REQUIRED` and enter `AWAITING_INPUT` with a precise reason and return state. Never infer a physical jurisdiction from an address alone or treat a missing registry match as proven unlicensed status.

Recovery resumes the first unfinished intake state. A saved party-resolution result is reused only while its input digest and referenced source versions still match.

## 3. Leg 2: Evidence retrieval

Purpose: create an inspectable evidence package before the analyst runs.

| Current state | Event | Next state | Guard and durable output |
|---|---|---|---|
| `CONTEXT_READY` | `START_EVIDENCE` | `EMBEDDING_QUERY` | Complete context snapshot exists; save factual narrative, query digest, and embedding model. |
| `EMBEDDING_QUERY` | `QUERY_EMBEDDED` | `SEARCHING_REGULATIONS` | Embedding is valid and has 1,024 dimensions; save vector/model/input references. |
| `SEARCHING_REGULATIONS` | `REGULATION_CANDIDATES_SAVED` | `SEARCHING_PRECEDENTS` | Use jurisdiction, tenant/scope, clearance, review, and validity filters; save candidate IDs, versions, and retrieval scores. |
| `SEARCHING_PRECEDENTS` | `PRECEDENT_CANDIDATES_SAVED` | `RERANKING_EVIDENCE` | Retrieve only eligible tenant precedents; save candidates or an explicit empty result. No precedent match is a valid search result. |
| `RERANKING_EVIDENCE` | `EVIDENCE_RERANKED` | `VALIDATING_EVIDENCE` | Save reranked clauses and linked applicability/exception references; keep regulation and precedent results distinguishable. |
| `VALIDATING_EVIDENCE` | `EVIDENCE_VALIDATED` | `EVIDENCE_READY` | Re-read authoritative source records and validate versions, review state, scope, effective intervals, and required text; save evidence digest. |

Transient embedding/search/reranking failures use `RETRY_WAIT`. Missing applicable clauses or unverifiable sources use `AWAITING_INPUT`; they do not become a clean finding. Retrieval and reranking scores remain relevance scores.

Recovery resumes the unfinished operation using saved context/query references. It does not regenerate a valid embedding because a later search failed. Once intake revalidates a changed context, invalidate downstream evidence and analysis snapshots and start its new evidence revision at `EMBEDDING_QUERY`.

Use `CONTEXT_STALE` to return to `VALIDATING_CONTEXT` when the context itself changed, and `EVIDENCE_STALE` to return to `EMBEDDING_QUERY` when the context remains valid but evidence changed. Both revoke stale approval/outbox permission and are available only before a possible external send.

## 4. Leg 3: Analysis

Purpose: turn the saved context and evidence into a constrained, cited finding. The analyst has no execution authority.

| Current state | Event | Next state | Guard and durable output |
|---|---|---|---|
| `EVIDENCE_READY` | `START_ANALYSIS` | `GENERATING_FINDING` | Context/evidence versions are current; save the exact input manifest, model, and prompt version. |
| `GENERATING_FINDING` | `FINDING_RETURNED` | `VALIDATING_FINDING` | Save provider output and input digest as an untrusted candidate finding. |
| `VALIDATING_FINDING` | `FINDING_VALIDATED` | `FINDING_READY` | Validate structure, citation membership, source versions, required facts, and supported claims; save the validated finding and digest. |

Allowed finding values remain `EVIDENCE_SUPPORTED_RISK` and `REVIEW_REQUIRED`. A structurally valid `REVIEW_REQUIRED` finding can reach `FINDING_READY`, but cannot qualify for automatic authorization. It records exactly which facts or judgment require review.

Malformed output and unsupported citations trigger a bounded regeneration through `RETRY_WAIT`, returning to `GENERATING_FINDING`. Exhaustion enters `AWAITING_INPUT` for analyst correction. Saved untrusted output is never passed off as a validated finding.

Recovery from `VALIDATING_FINDING` validates the saved candidate rather than calling the model again. A stale upstream snapshot returns to the earliest affected intake/evidence state before a new finding can be accepted.

## 5. Leg 4: Authorization

Purpose: decide whether this exact hold action is permitted under current authority and policy. Authorization is deterministic.

| Current state | Event | Next state | Guard and durable output |
|---|---|---|---|
| `FINDING_READY` | `START_POLICY_CHECK` | `EVALUATING_POLICY` | Finding is validated; build and persist an immutable proposed action, evidence references, proposal version, and digest. |
| `EVALUATING_POLICY` | `POLICY_AUTHORIZED` | `AUTHORIZED` | Tenant/target/action/authority/evidence checks pass; save the authorization, policy version, exact proposal digest, and pending outbox intent in one transaction. |
| `EVALUATING_POLICY` | `HUMAN_APPROVAL_REQUIRED` | `AWAITING_APPROVAL` | The action is eligible but exceeds the automatic limit; save reason codes and the version/digest the officer must review. |
| `AWAITING_APPROVAL` | `OFFICER_APPROVED` | `EVALUATING_POLICY` | Officer identity and tenant match; approval references the current proposal version/digest; persist the decision, then rerun all authorization guards. |
| `AWAITING_APPROVAL` | `OFFICER_REJECTED` | `DENIED` | Record the officer, reason, and rejected proposal version; no dispatchable action is produced. |
| `EVALUATING_POLICY` | `POLICY_DENIED` | `DENIED` | Invalid authority or prohibited action/target; save deterministic denial reason codes. |

Preserve the USD 250,000 automatic threshold from the enriched plan. Larger eligible proposals require an officer. An officer cannot waive invalid authority, another tenant's target, missing evidence, or a changed proposal by clicking approve.

`REVIEW_REQUIRED` findings, missing facts, or invalid evidence use `AWAITING_INPUT` for correction before reevaluation. Expired approval requires a new valid decision. An upstream correction creates new artifact/proposal revisions; old approvals remain historical and cannot authorize the replacement.

Recovery reuses a valid saved finding and proposal. If the authorization transaction committed, it also committed its unique outbox intent; replay does not insert another intent. An external submission may not occur in this leg.

## 6. Leg 5: Dispatch

Purpose: prepare the approved operation durably, then attempt its submission without confusing transport success with completion.

| Current state | Event | Next state | Guard and durable output |
|---|---|---|---|
| `AUTHORIZED` | `START_PREPARATION` | `PREPARING_ACTION` | Authorization and its unique pending outbox intent exist; record preparation attempt. |
| `PREPARING_ACTION` | `ACTION_PREPARATION_SUCCEEDED` | `ACTION_PREPARED` | Prepared payload matches the authorized action; persist operation ID, idempotency key, payload digest, and all connector recovery data before any send. |
| `ACTION_PREPARED` | `SUBMISSION_PERMITTED` | `SUBMITTING` | Atomically recheck authority, proposal/evidence/policy versions, pause control, lease, and fence; save a dispatch permit and attempt identity. |
| `SUBMITTING` | `CONNECTOR_ACCEPTED` | `SUBMITTED` | Save the connector's actual operation reference and response. Acceptance is not proof of the held effect. |
| `SUBMITTING` | `SUBMISSION_AMBIGUOUS` | `SUBMISSION_UNKNOWN` | Timeout, disconnect, or uncertain response after possible acceptance; save error class and the prepared identity, without generating a replacement. |

The dispatch-permit transaction serializes against tenant pause/policy/invalidation updates using a tenant control revision. A pause committed before that permit blocks the send. A pause committed afterward may encounter an already permitted send; the system must report and reconcile it rather than claim it was cancelled.

All policy and memory invalidation changes relevant to dispatch increment that tenant control revision atomically. In the permit transaction, a conditional write to that same control record creates a write conflict with concurrent governance changes; checking a stale snapshot without that write is insufficient.

A guard failure before any possible send returns to the appropriate policy/evidence state and marks the stale intent non-dispatchable. A model must never repair or rewrite an authorized payload during dispatch.

On restart, `PREPARING_ACTION` may repeat side-effect-free preparation. `ACTION_PREPARED` can obtain a fresh permit. Recovery from `SUBMITTING`, `SUBMITTED`, or `SUBMISSION_UNKNOWN` always probes the saved operation first. It never assumes that lack of a saved HTTP response means lack of an external effect.

## 7. Leg 6: Verification and finalization

Purpose: establish what actually happened externally, verify the intended effect, and finish the audit record.

| Current state | Event | Next state | Guard and durable output |
|---|---|---|---|
| `SUBMITTED` or `SUBMISSION_UNKNOWN` | `START_RECONCILIATION` | `RECONCILING` | A complete prepared-operation checkpoint exists; record the probe identity. Recovery from `SUBMITTING` uses the same transition. |
| `RECONCILING` | `PROBE_PENDING` | `AWAITING_EFFECT` | Provider recognizes the operation but confirmation is pending; save probe result and next probe time. |
| `AWAITING_EFFECT` | `PROBE_DUE` | `RECONCILING` | Timer is due and the worker holds the lease; probe the same operation. |
| `RECONCILING` | `PROBE_CONFIRMED` | `VERIFYING_EFFECT` | Save successful receipt/confirmation evidence; independently validate target, action identity, and resulting held state. |
| `VERIFYING_EFFECT` | `EFFECT_VERIFIED` | `EFFECT_CONFIRMED` | Receipt and effect agree with the authorized tenant, settlement, and operation; save verification evidence and digest. |
| `EFFECT_CONFIRMED` | `START_FINALIZATION` | `FINALIZING` | Verified effect checkpoint exists; prepare the final audit event and historical case snapshot. |
| `FINALIZING` | `FINAL_RECORD_COMMITTED` | `FINALIZED` | Atomically append final audit evidence, persist one historical case snapshot, and advance the FSM. |

`NOT_FOUND` does not by itself prove that resubmission is safe. The FSM records it and continues reconciliation unless the connector can establish authoritative absence. Only conclusive absence plus renewed dispatch guards permits a return to `ACTION_PREPARED` with the identical operation identity and payload. Otherwise use `MANUAL_REVIEW`; never create a new operation to escape uncertainty.

An authoritative rejection/revert with a confirmed absent hold emits `ACTION_FAILED` and enters terminal `ACTION_FAILED`. A successful receipt with the wrong target/effect, conflicting receipts, or an unresolved effect enters `MANUAL_REVIEW`. No automatic release or compensating money movement is part of this FSM.

Once any send might have occurred, governance changes may block further sends but cannot restart analysis into a replacement action while the old outcome remains unresolved. Preserve the execution checkpoint and reconcile first. If absence is conclusive but the saved payload can no longer be authorized, require operator resolution; do not silently replace it.

Recovery from `EFFECT_CONFIRMED` or `FINALIZING` retries local finalization only. It never submits the hold again. The resulting historical case is a completed workflow record; it does not automatically become an analyst-confirmed precedent eligible to authorize future actions.

An unavailable effect read during `VERIFYING_EFFECT` uses `PROBE_UNKNOWN` to schedule another read through `AWAITING_EFFECT`, or `RECONCILIATION_EXPIRED` to enter manual review. Exhausted local finalization uses `FINALIZATION_BLOCKED` with a finalization-only checkpoint. An officer's `FINALIZATION_RETRY_REQUESTED` then returns to `FINALIZING`; it cannot reenter dispatch or network reconciliation.

## 8. Shared wait states, retries, and terminal outcomes

| State | Entry conditions | Allowed exit |
|---|---|---|
| `RETRY_WAIT` | A safe-to-repeat read/computation/preparation step failed transiently; persist failed state, input digest, attempt, and due time. | `RETRY_DUE` returns to that exact state after its guards pass. A submission timeout cannot use this path to resend. |
| `AWAITING_INPUT` | Specific facts, citations, analysis, or a renewed valid approval are required; persist reason codes and the earliest affected return state. | An authorized correction event creates new input/artifact revisions and reenters that state. No unchanged-data resume or direct jump to dispatch. |
| `AWAITING_APPROVAL` | An otherwise eligible immutable proposal needs officer authority. | Version-bound approval returns to policy evaluation; rejection enters `DENIED`. |
| `MANUAL_REVIEW` | An external outcome remains unresolved or confirmed local finalization is blocked. | The saved checkpoint selects `RECONCILING` or local `FINALIZING`. Operator events cannot switch between these recovery boundaries. |

Shared waits derive their leg from their saved origin state. Every wait checkpoint stores its input digest/revision; a retry additionally requires a persisted due time and consumed attempt. Resume targets are validated against the failed computation or earliest affected prior state. A manual finalization checkpoint permits only local finalization recovery.

Default read/computation retry policy: three attempts total per state/input revision, with waits of two and four seconds. A valid provider `Retry-After` may extend a wait up to 60 seconds; longer or exhausted failures require input/operator attention. Persist attempts and timers so restart does not reset the budget. Deterministic invalid inputs are not retried.

Default verification polling is one second with a 120-second automated reconciliation deadline. Expiry enters `MANUAL_REVIEW` and explicitly leaves the external outcome unresolved. These are simulator/demo defaults, not blockchain finality guarantees. Lease and heartbeat defaults remain ten and three seconds; lease renewal runs independently of slow provider calls.

Terminal states are `REJECTED`, `DENIED`, `ACTION_FAILED`, and `FINALIZED`. Every terminal state has no automatic outgoing transitions. A new evaluation after a terminal result requires a new request key and references the earlier FSM; it cannot silently reopen the old instance.

Tenant pause is an orthogonal control, not a replacement business state. It prevents new submission permits while read-only reconciliation and local audit finalization remain available. Outbox delivery state mirrors transport bookkeeping; it is not a second business-state authority.

## 9. Exact example trace

For the same fictional USD 100,000 pending-settlement scenario used by the enriched plan:

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

The crash demonstration kills the worker after the simulator saves the hold but before the worker records acceptance. Recovery starts from persisted `SUBMITTING`, enters `RECONCILING`, probes the saved operation, and finalizes one effect. It does not replay intake, retrieval, analysis, or authorization.

## 10. Acceptance criteria and implementation boundary

1. Every state has a leg, valid entry events, guards, output requirements, and an explicit recovery rule. There is no generic caller-supplied `next_state` authorization.
2. A transition with an invalid event, stale revision/fence, expired lease, wrong tenant, or missing artifact cannot advance state or append a success event.
3. Duplicate events, duplicate worker delivery, and concurrent claims cannot produce duplicate outbox intents or external operations.
4. Restart during each evidence/analysis substep resumes from the saved checkpoint. Stale results cannot overwrite a newer context revision.
5. Missing jurisdiction, invalid citations, insufficient evidence, and `REVIEW_REQUIRED` findings cannot authorize a hold.
6. A USD 1.6 million proposal enters officer review. Approval for an old proposal or evidence revision cannot reach `AUTHORIZED` or obtain a dispatch permit.
7. Pause or evidence invalidation before the dispatch permit prevents submission. A previously permitted send is reported honestly and reconciled.
8. Crash or response loss during `SUBMITTING` probes first and finalizes one simulator effect. Repeated `NOT_FOUND` results alone cannot create a replacement action.
9. Receipt success without the expected held effect cannot finalize. A reverted/rejected action and an unknown outcome take distinct paths.
10. Restart during finalization cannot resend the hold or duplicate the historical case/audit record. A finalization/reporting error cannot release the protective hold.
11. The API exposes the current leg, precise state, last event, artifact references, wait reason, and next permitted event; the UI never equates submitted with finalized.
12. Terminal instances cannot be reopened by a retry or manual state edit. A deliberate new evaluation links to the previous instance.

The catalog and scaffold interfaces implement these names and expose the static transition definitions. Instance operations remain explicit 501 responses until the durable handlers are implemented.
