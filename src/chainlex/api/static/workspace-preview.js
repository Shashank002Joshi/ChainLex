const context = {
  origin: "scotiabank", destination: "dbs", amount: "100000.00", asset: "USDC", network: "ethereum-sepolia", adapter: "reviewed-demo-source-v1-to-context-v1", fixture_version: "audit-demo-v1",
  narrative: "Fictional USDC settlement from Canada to Singapore through a US intermediary.",
  sources: [
    { source_id: "ca-aml", title: "FINTRAC guidance overview", jurisdiction: "CA", url: "https://fintrac-canafe.canada.ca/guidance-directives/guidance-directives-eng", review_status: "UNVERIFIED" },
    { source_id: "us-aml", title: "FinCEN AML/CFT overview", jurisdiction: "US", url: "https://www.fincen.gov/resources", review_status: "UNVERIFIED" },
    { source_id: "sg-aml", title: "MAS AML/CFT overview", jurisdiction: "SG", url: "https://www.mas.gov.sg/regulation/anti-money-laundering", review_status: "UNVERIFIED" },
  ],
};
const routes = [
  { route_id: "configured-ca-us-sg", provenance: "configured_demo_corridor", banks: [{ bank_id: "scotiabank", jurisdiction: "CA" }, { bank_id: "jpmorgan_chase", jurisdiction: "US" }, { bank_id: "dbs", jurisdiction: "SG" }], outcome: "CONDITIONAL", unresolved_checks: 1, issues: ["UNVERIFIED_SOURCE_REFERENCES"], hop_count: 2 },
  { route_id: "discovered-ca-sg", provenance: "scripted_official_source_candidate", banks: [{ bank_id: "scotiabank", jurisdiction: "CA" }, { bank_id: "dbs", jurisdiction: "SG" }], outcome: "CONDITIONAL", unresolved_checks: 3, issues: ["UNVERIFIED_SOURCE_REFERENCES", "CONNECTIVITY_UNVERIFIED", "CANDIDATE_REQUIRES_HUMAN_VERIFICATION"], hop_count: 1 },
].map(r => ({ ...r, bank_checks: r.banks.map((b, i) => ({ bank_id: b.bank_id, position: i, outcome: i === 0 ? "PASS" : "NOT_APPLICABLE", reason: i === 0 ? "ORIGINATOR_ALLOWLISTED" : "ORIGINATOR_CHECK_ONLY_AT_SOURCE" })), jurisdiction_checks: [...new Set(r.banks.map(b => b.jurisdiction))].map(jurisdiction => ({ jurisdiction, outcome: "REVIEW", reason: "NO_VERIFIED_EVIDENCE", rule_ids: [] })) }));
const gates = [
  { gate_id: "evidence-review", title: "Evidence & applicability", reason: "Review unverified source references and confirm the requirements that apply to this case." },
  { gate_id: "corridor-verification", title: "Discovered corridor verification", reason: "Confirm bank connectivity before considering the direct Canada-to-Singapore candidate." },
  { gate_id: "final-signoff", title: "Final officer sign-off", reason: "Review the complete audit after the preceding gates have recorded decisions." },
].map(gate => ({ ...gate, required: true, status: "PENDING" }));
const eventTypes = [
  ["REQUEST_ACCEPTED", "bank_a:analyst"], ["CONTEXT_VALIDATED", "durable_completion"],
  ["ACTION_PERMITTED", "governed_memory"], ["QUERY_EMBEDDED", "governed_memory"],
  ["EVIDENCE_RETRIEVED", "governed_memory"], ["ACTION_PERMITTED", "auditable_action"],
  ["ANALYSIS_VALIDATED", "auditable_action"], ["REPORT_PREPARED", "durable_completion"],
  ["DRAFT_PUBLISHED", "durable_completion"],
];
export function previewState(scenario = "corridor_audit") {
  const audit = {
    audit_id: "sample-001", tenant_id: "sample_workspace", revision: 9, scenario, mode: "scripted_demo", state: "AWAITING_HUMAN_REVIEW", initiated_by: "Sample analyst", analysis_digest: "0".repeat(64), created_at: "2026-11-14T16:30:00Z", updated_at: "2026-11-14T16:30:24Z", gates: structuredClone(gates), checkpoint: {
      context: structuredClone(context), evidence: { regulations: [], memories: [], memory_search_status: "complete", regulation_search_status: "complete", embedding_model: "voyage-finance-2" },
      analysis: { recommended_route_id: routes[0].route_id, verdict: "CONDITIONAL", finding: "REVIEW_REQUIRED", explanation: "The configured corridor has fewer unresolved checks. Source applicability and any discovered bank relationships still require human review.", routes: structuredClone(routes), memory_comparison: { behavior_changed: false, without_memory: { recommended_route_id: routes[0].route_id }, with_memory: { recommended_route_id: routes[0].route_id }, interpretation: "No prior memory affected this sample assessment." } },
      draft_receipt: { version: 1, verified: false },
    },
  };
  const events = eventTypes.map(([event_type, actor_id], i) => ({ sequence: i + 1, event_type, actor_id, occurred_at: `2026-11-14T16:30:${String(i * 3).padStart(2, "0")}Z`, payload: {} }));
  if (scenario === "memory_influence") {
    audit.checkpoint.evidence.memories = [{ memory_id: "sample-intermediary-review", version: 1, narrative: "A previous fictional case required additional intermediary ownership documentation.", required_gate: "Confirm beneficial ownership documentation for the intermediary.", route_id: routes[0].route_id, valid_until: "2026-12-14T16:30:00Z", review_status: "REVIEWED_DEMO", scope: "scripted_demo", content_hash: "0".repeat(64) }];
    audit.gates.splice(2, 0, { gate_id: "memory-sample-review", title: "Precedent-driven review", reason: "Confirm beneficial ownership documentation for the intermediary.", required: true, status: "PENDING" });
    audit.checkpoint.analysis.routes[0].unresolved_checks = 4;
    audit.checkpoint.analysis.recommended_route_id = routes[1].route_id;
    audit.checkpoint.analysis.memory_comparison.behavior_changed = true;
    audit.checkpoint.analysis.memory_comparison.with_memory.recommended_route_id = routes[1].route_id;
    audit.checkpoint.analysis.memory_comparison.interpretation = "This sample memory adds a review gate and changes the route ranking; it does not establish regulatory clearance.";
  }
  if (scenario === "no_suitable_route") {
    audit.checkpoint.analysis.verdict = "NO_SUITABLE_ROUTE";
    audit.checkpoint.analysis.recommended_route_id = null;
    audit.checkpoint.analysis.routes.forEach(r => { r.outcome = "DENY"; r.issues.push("BANK_ADMISSION_DENIED"); r.bank_checks[0].outcome = "DENY"; });
    audit.checkpoint.analysis.explanation = "Neither sample corridor passes originating-bank admission. Human review cannot override that denial.";
  }
  if (scenario === "unsupported_schema") { audit.state = "MANUAL_REVIEW"; audit.error_code = "SOURCE_SCHEMA_NOT_SUPPORTED"; audit.gates = []; audit.checkpoint = {}; }
  return { audit, events, reports: scenario === "unsupported_schema" ? [] : [{ version: 1, kind: "DRAFT", published_at: "2026-11-14T16:30:24Z", sample: true, verified: false }] };
}
