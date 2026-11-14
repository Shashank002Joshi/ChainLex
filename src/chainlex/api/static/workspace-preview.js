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
      context: { ...structuredClone(context), routes: structuredClone(routes) }, evidence: { regulations: [], memories: [], memory_search_status: "complete", regulation_search_status: "complete", embedding_model: "voyage-finance-2" },
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

export function sampleVerification(payload) {
  const scenario = payload?.scenario || "custom";
  const amount = payload?.amount || 100000;
  const ben = payload?.beneficiary_address || "0x2222222222222222222222222222222222222222";
  const signer = payload?.initiator_address || "0xBCfe83238c0f3E11ACA5dE16Fa697b6fA55070BA";
  const isSanctions = scenario === "sanctions_blocked" || ben.toLowerCase().includes("57cb");
  const isTravel = scenario === "cross_country";
  const isHighValue = scenario === "binance_hack" || amount >= 1000000;

  if (isSanctions) {
    return {
      overall_status: "BLOCK",
      settlement_id: "0x57cb113ffba59eb1965bb7ee0b9dfba7ff291a4f000000000000000000000000",
      legs: {
        leg_1_validation: {
          leg: "validation", status: "PASS", amount,
          authenticated_originator: signer,
          beneficiary_address: ben,
        },
        leg_2_admission: { leg: "admission", status: "PASS", admission_outcome: "PASS" },
        leg_3_evidence: { leg: "discovery", status: "PASS", discovered_rules_count: 12 },
        leg_4_analysis: {
          leg: "court_analysis", status: "BLOCK",
          court_deliberation: {
            prosecutor_submission: {
              advocated_verdict: "DENY",
              reasoning_summary: "CRITICAL VIOLATION: Beneficiary address is identified on active OFAC Specially Designated Nationals (SDN) sanctions list under Executive Order 14024.",
              charges_or_exemptions: ["COUNT 1: Statutory OFAC Virtual Currency Sanctions Breach", "COUNT 2: Prohibition on Facilitating Transfers to Blocked Addresses"],
              statutory_citations: ["US-OFAC-SANCTIONS-001 (Virtual Currency Scope)", "US-OFAC-SCREENING-001 (Risk-Based Screening)"],
            },
            defense_submission: {
              advocated_verdict: "HOLD",
              reasoning_summary: "Defense acknowledges matching identifier. No safe harbor applies under unilateral OFAC sanctions restrictions. Recommends protective freeze.",
              charges_or_exemptions: ["No applicable general license or humanitarian safe harbor"],
              statutory_citations: ["OFAC Virtual Currency Guidance Section 560.540"],
            },
            cco_determination: {
              advocated_verdict: "BLOCK",
              action_ordered: "PROTECTIVE_HOLD",
              reasoning_summary: "CHIEF COMPLIANCE OFFICER BINDING ORDER: Sanctions block sustained. Prosecutor charges proven. Mandatory on-chain protective freeze dispatched to SettlementHub.",
            },
          },
        },
        leg_5_dispatch: {
          leg: "execution", status: "CONFIRMED",
          tx_hash: "0xf5de4971392bc7ec1ce5729c5678ebd8e91c5d32948325bf091a4f52cb099de6",
          explorer_url: "https://sepolia.etherscan.io/tx/0xf5de4971392bc7ec1ce5729c5678ebd8e91c5d32948325bf091a4f52cb099de6",
          effect: "isSettlementHeld(0x57cb113ffba59eb1965bb7ee0b9dfba7ff291a4f...) == true",
          state_transitions: ["SUBMITTING -> SUBMITTED -> VERIFYING_EFFECT -> EFFECT_CONFIRMED"],
        },
        leg_6_audit: {
          leg: "audit", status: "FINALIZED",
          canonical_document_hash: "0xf5de4971392bc7ec1ce5729c5678ebd8e91c5d32948325bf091a4f52cb099de6",
          merkle_root: "0xf5de4971392bc7ec1ce5729c5678ebd8e91c5d32948325bf091a4f52cb099de6",
          state_transitions: ["FINALIZING -> FINALIZED"],
        },
      },
    };
  }

  if (isTravel) {
    return {
      overall_status: "HOLD",
      settlement_id: "0x4444444444444444444444444444444444444444000000000000000000000000",
      legs: {
        leg_1_validation: {
          leg: "validation", status: "PASS", amount,
          authenticated_originator: signer,
          beneficiary_address: ben,
        },
        leg_2_admission: { leg: "admission", status: "HOLD", admission_outcome: "HOLD", error: "Missing required Travel Rule data for cross-border corridor." },
        leg_3_evidence: { leg: "discovery", status: "PASS", discovered_rules_count: 12 },
        leg_4_analysis: {
          leg: "court_analysis", status: "HOLD",
          court_deliberation: {
            prosecutor_submission: {
              advocated_verdict: "HOLD",
              reasoning_summary: "Statutory breach: Required originator and beneficiary identification payload is missing under FINTRAC PCMLTFA regulations.",
              charges_or_exemptions: ["COUNT 1: FINTRAC Travel Rule Omission"],
              statutory_citations: ["CA-FINTRAC-TRAVEL-001", "CA-FINTRAC-MISSING-001"],
            },
            defense_submission: {
              advocated_verdict: "HOLD",
              reasoning_summary: "Defense requests provisional hold pending receipt of off-chain Travel Rule data packet.",
              charges_or_exemptions: ["Provisional hold requested"],
              statutory_citations: ["FATF Recommendation 16"],
            },
            cco_determination: {
              advocated_verdict: "HOLD",
              action_ordered: "REQUIRE_TRAVEL_RULE",
              reasoning_summary: "CCO ORDER: Settlement held pending complete IVMS101 travel rule submission.",
            },
          },
        },
        leg_5_dispatch: { leg: "execution", status: "HELD_PENDING_DOCS", state_transitions: ["HELD_AT_ADMISSION"] },
        leg_6_audit: {
          leg: "audit", status: "FINALIZED",
          merkle_root: "0x88bb4421aa47bb12cc33dd55ee77ff99112233445566778899aabbccddeeff00",
        },
      },
    };
  }

  // Default: Compliant Clean Settlement
  return {
    overall_status: "PASS",
    settlement_id: "0x9b782296f9f4459ea870db11f68c99889b782296f9f4459ea870db11f68c9988",
    legs: {
      leg_1_validation: {
        leg: "validation", status: "PASS", amount,
        authenticated_originator: signer,
        beneficiary_address: ben,
      },
      leg_2_admission: { leg: "admission", status: "PASS", admission_outcome: "PASS" },
      leg_3_evidence: { leg: "discovery", status: "PASS", discovered_rules_count: 12 },
      leg_4_analysis: {
        leg: "court_analysis", status: "PASS",
        court_deliberation: {
          prosecutor_submission: {
            advocated_verdict: "APPROVE",
            reasoning_summary: "Prosecutor review reveals no statutory violations or missing controls across Canadian (FINTRAC), US (FinCEN/OFAC), and Singapore (MAS) regimes.",
            charges_or_exemptions: ["Sanctions clear across OFAC, MAS, and Canadian databases", "KYC & CDD documentation verified on file"],
            statutory_citations: ["CA-FINTRAC-TRAVEL-001", "SG-MAS-CDD-001", "US-OFAC-SANCTIONS-001"],
          },
          defense_submission: {
            advocated_verdict: "APPROVE",
            reasoning_summary: "Defense demonstrates full satisfaction of statutory safe harbors and correspondent bank admission criteria. Transaction should proceed unimpeded.",
            charges_or_exemptions: ["Sanctions screening is fully CLEAR", "Full Tier-1 Customer Due Diligence on file", "FATF reciprocal safe harbor applicable"],
            statutory_citations: ["FATF Recommendation 16 Safe Harbor", "MAS Notice 626 Reciprocal Intermediary Carve-Out"],
          },
          cco_determination: {
            advocated_verdict: "PASS",
            action_ordered: "CLEAR_SETTLEMENT",
            reasoning_summary: "CHIEF COMPLIANCE OFFICER VERDICT: FULL STATUTORY CLEARANCE. Defense arguments sustained. All compliance controls and admission policies satisfied. Cleared for atomic settlement on Ethereum Sepolia.",
          },
        },
      },
      leg_5_dispatch: {
        leg: "execution", status: "CLEARED",
        message: "No protective hold required; transaction approved for settlement.",
        state_transitions: ["SUBMITTING -> SUBMITTED -> EFFECT_CONFIRMED (CLEARED)"],
      },
      leg_6_audit: {
        leg: "audit", status: "FINALIZED",
        canonical_document_hash: "0x22176520575bfb0890148a21634fed4d3f4ffc9b790bc74d219ab39f1f3348d7",
        merkle_root: "0x22176520575bfb0890148a21634fed4d3f4ffc9b790bc74d219ab39f1f3348d7",
        state_transitions: ["FINALIZING -> FINALIZED"],
      },
    },
  };
}
