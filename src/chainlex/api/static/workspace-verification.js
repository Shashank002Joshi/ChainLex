import { esc, humanize, icon } from "./workspace-core.js";

export function verificationView(result) {
  if (!result) return "";
  const court = result.legs?.leg_4_analysis?.court_deliberation;
  const submissions = court ? [
    ["Regulatory Prosecutor (Statutory Charges)", court.prosecutor_submission],
    ["Defense Counsel (Safe Harbors & Mitigations)", court.defense_submission],
    ["Chief Compliance Officer (Binding Determination)", court.cco_determination]
  ] : [];
  const leg1 = result.legs?.leg_1_validation;
  const leg5 = result.legs?.leg_5_dispatch;
  const leg6 = result.legs?.leg_6_audit;
  const isPass = result.overall_status === "PASS";
  const isBlocked = result.overall_status === "BLOCK" || court?.cco_determination?.action_ordered === "PROTECTIVE_HOLD";

  let onchainBanner = "";
  if (isBlocked && leg5?.tx_hash) {
    onchainBanner = `
      <div class="onchain-action-banner block">
        <div class="onchain-banner-head">
          <h3>🚨 Protective On-Chain Hold Dispatched</h3>
          <span class="badge badge-danger">ON-CHAIN FREEZE</span>
        </div>
        <p class="onchain-banner-details">
          Statutory violation confirmed. An automated protective freeze was dispatched to the Sepolia <code>SettlementHub</code> contract to halt settlement.
          <br><strong>Status:</strong> ${esc(leg5.status || "CONFIRMED")}
          ${leg5.effect ? `<br><strong>Contract State:</strong> <code>${esc(leg5.effect)}</code>` : ""}
        </p>
        <a href="${esc(leg5.explorer_url || `https://sepolia.etherscan.io/tx/${leg5.tx_hash}`)}" target="_blank" rel="noopener noreferrer" class="onchain-explorer-btn danger">
          ${icon("external")} View Sepolia Hold on Etherscan (${leg5.tx_hash.slice(0, 10)}…)
        </a>
      </div>
    `;
  } else if (isPass) {
    onchainBanner = `
      <div class="onchain-action-banner pass">
        <div class="onchain-banner-head">
          <h3>✅ Multi-Agent Compliance Cleared</h3>
          <span class="badge badge-good">AUTHORIZED</span>
        </div>
        <p class="onchain-banner-details">
          All 6 compliance legs verified across 12 statutory regulations (FINTRAC, OFAC, MAS). Both accounts are cleared. Route is authorized for final atomic settlement on Ethereum Sepolia.
        </p>
        <button type="button" class="button button-primary" data-action="proceed-submit" style="margin-top:6px">
          ${icon("send")} Submit &amp; Settle on Sepolia
        </button>
      </div>
    `;
  }

  return `
    <section class="panel" style="margin-top:22px">
      <div class="panel-head">
        <h2>${icon("shield")}Compliance Preflight &amp; Court Verification</h2>
        <span class="badge badge-${isPass ? "good" : "danger"}">${esc(humanize(result.overall_status))}</span>
      </div>
      <div class="panel-padding">
        ${onchainBanner}

        ${leg1 ? `
          <div class="memory-record" style="margin-top:14px">
            <div class="detail-heading">
              <h3>Two-Account Corridor Evaluation</h3>
              <span class="badge">${esc(leg1.amount || "—")} USDC</span>
            </div>
            <p><strong>Account 1 (Originator):</strong> <span class="mono">${esc(leg1.authenticated_originator || "—")}</span></p>
            <p><strong>Account 2 (Beneficiary):</strong> <span class="mono">${esc(leg1.beneficiary_address || "—")}</span></p>
            <p><strong>Settlement ID:</strong> <span class="mono">${esc(result.settlement_id || "—")}</span></p>
          </div>
        ` : ""}

        <div class="section-heading" style="margin:20px 0 10px">
          <h2>Deliberative Compliance Court</h2>
          <span class="hint">Adversarial agent roles · Binding decision</span>
        </div>

        ${submissions.map(([name, argument]) => `
          <div class="memory-record">
            <div class="detail-heading">
              <h3>${name}</h3>
              <span class="badge badge-${argument.advocated_verdict === "APPROVE" ? "good" : "danger"}">${esc(humanize(argument.advocated_verdict))}</span>
            </div>
            <p>${esc(argument.reasoning_summary)}</p>
            ${argument.charges_or_exemptions?.length ? `<ul class="text-note">${argument.charges_or_exemptions.map(item => `<li>${esc(item)}</li>`).join("")}</ul>` : ""}
            ${argument.statutory_citations?.length ? `<p class="text-note" style="margin-top:4px"><strong>Citations:</strong> ${esc(argument.statutory_citations.join(", "))}</p>` : ""}
          </div>
        `).join("")}

        ${leg6?.merkle_root ? `
          <div class="memory-record" style="margin-top:14px">
            <div class="detail-heading">
              <h3>Leg 6: Cryptographic State Pinning &amp; Merkle Root</h3>
              <span class="badge">Tamper-Evident</span>
            </div>
            <p class="mono text-wrap"><strong>Merkle Root:</strong> ${esc(leg6.merkle_root)}</p>
            <p class="mono text-wrap"><strong>Document SHA-256:</strong> ${esc(leg6.canonical_document_hash || "—")}</p>
          </div>
        ` : ""}

        <details class="view-reasoning" style="margin-top:14px">
          <summary>Detailed 6-Leg Execution Trace</summary>
          ${Object.entries(result.legs || {}).map(([key, leg]) => `
            <div class="memory-record">
              <h3>${esc(humanize(leg.leg || key))} · ${esc(humanize(leg.status || leg.admission_outcome || leg.final_verdict || "Evaluated"))}</h3>
              ${leg.error ? `<p style="color:var(--danger)">${esc(leg.error)}</p>` : ""}
              ${(leg.state_transitions || []).map(step => `<p class="mono text-wrap">${esc(step)}</p>`).join("")}
            </div>
          `).join("")}
        </details>
      </div>
    </section>
  `;
}

export function verificationPayload(form, signer) {
  const fields = Object.fromEntries(new FormData(form));
  const reverse = fields.route_id === "dbs-jpmorgan-scotiabank-demo";
  const mode = fields.verification_mode || "simulated";
  return {
    scenario: fields.verification_scenario || "custom",
    mode: mode,
    amount: Number(fields.amount || 100000.0),
    symbol: "USDC",
    decimals: 6,
    beneficiary_address: fields.beneficiary,
    initiator_address: signer || "0x1111111111111111111111111111111111111111",
    origin_bank: reverse ? "dbs" : "scotiabank",
    origin_country: reverse ? "SG" : "CA",
    inter_banks: ["jpmorgan_chase"],
    inter_countries: ["US"],
    dest_bank: reverse ? "scotiabank" : "dbs",
    dest_country: reverse ? "CA" : "SG",
  };
}
