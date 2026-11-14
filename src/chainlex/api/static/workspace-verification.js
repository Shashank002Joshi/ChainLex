import { esc, humanize, icon } from "./workspace-core.js";

export function verificationView(result) {
  if (!result) return "";
  const court = result.legs?.leg_4_analysis?.court_deliberation;
  const submissions = court ? [["Regulatory prosecutor", court.prosecutor_submission], ["Defense counsel", court.defense_submission], ["Chief compliance officer", court.cco_determination]] : [];
  return `<section class="panel" style="margin-top:22px"><div class="panel-head"><h2>${icon("shield")}Preflight review</h2><span class="badge badge-${result.overall_status === "PASS" ? "good" : "warning"}">${esc(humanize(result.overall_status))}</span></div><div class="panel-padding"><p class="text-note">Deterministic demo assessment · Simulated effects. This preflight is separate from the durable audit and human sign-off.</p>${submissions.map(([name, argument]) => `<div class="memory-record"><div class="detail-heading"><h3>${name}</h3><span class="badge">${esc(humanize(argument.advocated_verdict))}</span></div><p>${esc(argument.reasoning_summary)}</p>${argument.charges_or_exemptions?.length ? `<ul class="text-note">${argument.charges_or_exemptions.map(item => `<li>${esc(item)}</li>`).join("")}</ul>` : ""}${argument.statutory_citations?.length ? `<p>References: ${esc(argument.statutory_citations.join(", "))}</p>` : ""}</div>`).join("")}<details class="view-reasoning"><summary>Completed preflight trace</summary>${Object.entries(result.legs || {}).map(([key, leg]) => `<div class="memory-record"><h3>${esc(humanize(leg.leg || key))} · ${esc(humanize(leg.status || leg.admission_outcome || leg.final_verdict || "Evaluated"))}</h3>${leg.error ? `<p>${esc(leg.error)}</p>` : ""}${(leg.state_transitions || []).map(step => `<p class="mono text-wrap">${esc(step)}</p>`).join("")}</div>`).join("")}</details></div></section>`;
}

export function verificationPayload(form) {
  const fields = Object.fromEntries(new FormData(form));
  const reverse = fields.route_id === "dbs-jpmorgan-scotiabank-demo";
  return { scenario: fields.verification_scenario || "custom", mode: "simulated", amount: Number(fields.amount), symbol: "USDC", decimals: 6, beneficiary_address: fields.beneficiary, initiator_address: form.querySelector("#preflight-originator")?.value || "0x1111111111111111111111111111111111111111", origin_bank: reverse ? "dbs" : "scotiabank", origin_country: reverse ? "SG" : "CA", inter_banks: ["jpmorgan_chase"], inter_countries: ["US"], dest_bank: reverse ? "scotiabank" : "dbs", dest_country: reverse ? "CA" : "SG" };
}
