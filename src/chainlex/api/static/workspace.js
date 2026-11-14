import { verificationPayload, verificationView } from "./workspace-verification.js";
import { AGENTS, SCENARIOS, WorkspaceApi, esc, fillIcons, icon, sepoliaReference } from "./workspace-core.js";
import { previewState } from "./workspace-preview.js";
import { activityView, eventRows, reportsView, transactionResult, transactionsView, workspaceView } from "./workspace-view.js";

const $ = selector => document.querySelector(selector);
const state = {
  ...previewState(), preview: true, api: null, agent: AGENTS[0].id, eventFilter: "", feedPaused: false,
  lastSynced: null, connectionError: false, scenarios: SCENARIOS, chainReference: null,
  transaction: null, transactionConfig: null, transactionBusy: false,
};
let pollTimer, toastTimer, generation = 0, activeController, transactionTimer;
let lastRendered = "", returnFocus;
const viewName = () => ["workspace", "reports", "activity", "transactions"].includes(location.hash.slice(1)) ? location.hash.slice(1) : "workspace";
const titles = { workspace: ["Audit workspace", "A clear view of every agent, decision, and outcome."], reports: ["Audit reports", "The complete record, from first assessment to final review."], activity: ["Activity", "Follow every saved action and decision in the audit."], transactions: ["Create transaction", "An upstream settlement request, signed by your backend."] };

function toast(message) { clearTimeout(toastTimer); const el = $("#toast"); el.textContent = message; el.hidden = false; toastTimer = setTimeout(() => { el.hidden = true; }, 4000); }
function showError(error) { const el = $("#error-banner"); el.innerHTML = `<span>${esc(error.message || error)}</span><button class="text-button" data-action="refresh">Retry ${icon("cycle")}</button>`; el.hidden = false; }
function clearError() { $("#error-banner").hidden = true; }
function saveUrl(auditId) { const url = new URL(location.href); if (auditId) url.searchParams.set("audit", auditId); else url.searchParams.delete("audit"); history.replaceState(null, "", url); }
function resetRequest() { generation++; clearTimeout(pollTimer); activeController?.abort(); activeController = null; }
function downloadBlob(blob, filename) { const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = filename; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }

function render(force = false) {
  const view = viewName();
  const [title, description] = titles[view];
  $("#page-title").textContent = title; $("#page-description").textContent = description; $("#breadcrumb-page").textContent = title;
  $("#audit-short-id").textContent = view === "transactions" ? "NEW REQUEST" : state.audit?.audit_id || "NEW SESSION";
  document.querySelector(".heading-actions").hidden = view === "transactions";
  $("#report-count").textContent = state.reports.length;
  $("#footer-state").textContent = state.preview ? "Scripted demo · Preview data" : state.connectionError ? "Connection interrupted · Retrying" : "Scripted reasoning · Connected API";
  document.querySelectorAll("[data-nav]").forEach(link => { if (link.dataset.nav === view) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current"); });
  const key = JSON.stringify([view, state.audit, state.reports, state.events, state.agent, state.preview, state.feedPaused, state.connectionError, state.chainReference, state.transaction, state.transactionConfig]);
  if (!force && key === lastRendered) return;
  lastRendered = key;
  if (view === "transactions" && $("#transaction-form") && !force) return;
  const transactionFields = view === "transactions" && $("#transaction-form") ? Object.fromEntries(new FormData($("#transaction-form"))) : null;
  const focusId = document.activeElement?.id;
  const focusAgent = document.activeElement?.dataset.agent;
  const detailsOpen = [...document.querySelectorAll("details[open]")].map(el => el.querySelector("summary")?.textContent);
  const activityScroll = document.querySelector(".activity-list:not(.audit-events)")?.scrollTop || 0;
  $("#workspace-content").innerHTML = view === "reports" ? reportsView(state) : view === "activity" ? activityView(state) : view === "transactions" ? transactionsView(state) : workspaceView(state);
  if (transactionFields) Object.entries(transactionFields).forEach(([key, value]) => { const field = document.querySelector(`#transaction-form [name="${key}"]`); if (field) field.value = value; });
  document.querySelectorAll("details").forEach(el => { if (detailsOpen.includes(el.querySelector("summary")?.textContent)) el.open = true; });
  const list = document.querySelector(".activity-list:not(.audit-events)"); if (list) list.scrollTop = activityScroll;
  if (focusAgent) document.querySelector(`[data-agent="${focusAgent}"]`)?.focus({ preventScroll: true });
  else if (focusId && document.getElementById(focusId)) document.getElementById(focusId).focus({ preventScroll: true });
}

function showDialog(title, content, eyebrow = "WORKSPACE") {
  const dialog = $("#action-dialog"); returnFocus = document.activeElement;
  $("#dialog-title").textContent = title; $("#dialog-eyebrow").textContent = eyebrow;
  $("#dialog-content").innerHTML = content;
  if (!dialog.open) dialog.showModal();
}
function closeDialog() { $("#action-dialog").close(); }
function dialogForm(content, submitLabel, extra = "") { return `<form id="dialog-form">${content}<div id="form-error" class="field-error" role="alert" hidden></div><div class="dialog-actions">${extra}<button class="button button-secondary" type="button" data-action="cancel">Cancel</button><button class="button button-primary" type="submit">${submitLabel}</button></div></form>`; }
function bindForm(handler) {
  $("#dialog-form").addEventListener("submit", async event => {
    event.preventDefault(); const form = event.currentTarget;
    if (!form.reportValidity()) return;
    const submit = event.submitter || form.querySelector('[type="submit"]');
    const original = submit.innerHTML;
    form.querySelectorAll("button").forEach(b => { b.disabled = true; });
    submit.innerHTML = '<span class="spinner"></span>Working…'; $("#form-error").hidden = true;
    try { await handler(new FormData(form)); }
    catch (error) { if (error.name !== "AbortError") { const field = $("#form-error"); if (field) { field.textContent = error.message; field.hidden = false; } else showError(error); } }
    finally { form.querySelectorAll("button").forEach(b => { b.disabled = false; }); submit.innerHTML = original; }
  });
}
function connectDialog() {
  showDialog(state.api ? "Workspace connection" : "Connect your workspace", dialogForm(`<p class="dialog-copy">Use the access tokens configured on your backend. Tokens stay in this tab’s memory and are cleared when you disconnect or reload.</p><div class="field"><label for="access-token">Workspace access token</label><input id="access-token" name="token" type="password" required autocomplete="off" spellcheck="false"></div><div class="field"><label for="officer-token">Officer token <span class="hint">(optional)</span></label><input id="officer-token" name="officer" type="password" autocomplete="off" spellcheck="false"><small>Needed to record human gate decisions. You can also provide it when reviewing a gate.</small></div>`, "Connect workspace", state.api ? '<button class="text-button" type="button" data-action="disconnect">Disconnect</button>' : ""));
  bindForm(async form => {
    const api = new WorkspaceApi(String(form.get("token")).trim(), String(form.get("officer") || "").trim());
    const scenarios = await api.request("/api/audits/scenarios");
    if (!scenarios.scenarios || typeof scenarios.scenarios !== "object") throw new Error("The backend returned an unsupported audit contract.");
    resetRequest(); state.api = api; state.scenarios = scenarios.scenarios; state.preview = false;
    state.transaction = null; state.transactionConfig = null; state.verification = null; state.chainReference = null;
    state.audit = null; state.events = []; state.reports = []; state.lastSynced = null; state.connectionError = false; state.feedPaused = false;
    $("#mode-banner").innerHTML = `<span><span class="live-dot"></span><strong>Connected workspace</strong><span class="banner-detail">Scripted agents · Real workflow events and saved reports</span></span><button id="connect-banner" class="text-button">Connection settings ${icon("arrow")}</button>`;
    $("#connection-label").innerHTML = "Connected workspace<small>Credentials held in this tab</small>";
    clearError(); closeDialog(); render(true); toast("Workspace connected");
    loadTransactionConfig();
    const auditId = new URL(location.href).searchParams.get("audit"); if (auditId) await openAudit(auditId);
  });
}
function disconnect() {
  resetRequest(); clearTimeout(transactionTimer); state.api = null; state.preview = true;
  Object.assign(state, previewState(), { transaction: null, transactionConfig: null, verification: null, chainReference: null, connectionError: false });
  saveUrl(null); closeDialog(); clearError();
  $("#mode-banner").innerHTML = `<span><span class="preview-dot"></span><strong>Preview workspace</strong><span class="banner-detail">Sample data to explore the experience. No agents are running.</span></span><button id="connect-banner" class="text-button">Connect workspace ${icon("arrow")}</button>`;
  $("#connection-label").innerHTML = "Preview workspace<small>Connect to your audit API</small>";
  render(true); toast("Disconnected. Credentials cleared.");
}
function newAuditDialog() {
  showDialog("Start a new audit", dialogForm(`<p class="dialog-copy">${state.preview ? "Explore a sample scenario, or connect your workspace to run the real workflow." : "The worker will run all three agents and pause at the required human gates."}</p><div class="field"><label for="audit-scenario">Audit scenario</label><select id="audit-scenario" name="scenario">${Object.entries(state.scenarios).map(([id, description]) => `<option value="${esc(id)}">${esc(description)}</option>`).join("")}</select></div>`, state.preview ? "Open sample audit" : "Start audit"), "NEW AUDIT");
  const requestKey = crypto.randomUUID();
  bindForm(async form => {
    const scenario = String(form.get("scenario"));
    if (state.preview) { Object.assign(state, previewState(scenario)); state.agent = AGENTS[0].id; state.chainReference = null; closeDialog(); location.hash = "workspace"; render(true); toast("Sample audit loaded. No live actions performed."); return; }
    const audit = await state.api.request("/api/audits", { method: "POST", body: { scenario, idempotency_key: requestKey } });
    resetRequest(); state.audit = audit; state.events = []; state.reports = []; state.agent = AGENTS[0].id;
    state.chainReference = null; state.feedPaused = false; saveUrl(audit.audit_id); closeDialog(); location.hash = "workspace"; render(true); poll();
  });
}
function openAuditDialog() {
  if (state.preview) { connectDialog(); return; }
  showDialog("Open an existing audit", dialogForm('<p class="dialog-copy">Paste an audit ID to restore its saved agent outputs, decisions, and reports.</p><div class="field"><label for="existing-audit">Audit ID</label><input id="existing-audit" name="audit" required maxlength="128" spellcheck="false" autocomplete="off" placeholder="audit-…"></div>', "Open audit"));
  bindForm(async form => { await openAudit(String(form.get("audit")).trim()); closeDialog(); });
}
async function openAudit(id) {
  const audit = await state.api.request(`/api/audits/${encodeURIComponent(id)}`);
  resetRequest(); state.audit = audit; state.events = []; state.reports = []; state.feedPaused = false; state.chainReference = null;
  saveUrl(audit.audit_id); location.hash = "workspace"; render(true); await poll();
}
async function poll() {
  clearTimeout(pollTimer);
  if (!state.api || !state.audit || state.preview || state.feedPaused || document.hidden) return;
  activeController?.abort();
  const currentGeneration = ++generation, auditId = state.audit.audit_id, api = state.api;
  const controller = new AbortController(); activeController = controller;
  const timeout = setTimeout(() => controller.abort(), 12000);
  try {
    const prefix = `/api/audits/${encodeURIComponent(auditId)}`;
    const after = state.events.at(-1)?.sequence || 0;
    const results = await Promise.allSettled([api.request(prefix, { signal: controller.signal }), api.request(`${prefix}/events?after_seq=${after}`, { signal: controller.signal }), api.request(`${prefix}/reports`, { signal: controller.signal })]);
    if (currentGeneration !== generation) return;
    const failure = results.find(result => result.status === "rejected");
    if (failure) throw failure.reason;
    const [audit, events, reports] = results.map(r => r.value);
    if (!Array.isArray(events) || !Array.isArray(reports)) throw new Error("The audit API returned an unsupported response.");
    state.audit = audit;
    const known = new Set(state.events.map(e => e.sequence));
    const additions = events.filter(e => !known.has(e.sequence));
    state.events = [...state.events, ...additions].sort((a, b) => a.sequence - b.sequence).slice(-500);
    state.reports = reports; state.lastSynced = new Date().toISOString(); state.connectionError = false; clearError();
    if (additions.length) $("#announcements").textContent = `${additions.length} new audit events. ${humanState(audit.state)}.`;
    render();
  } catch (error) {
    if (currentGeneration !== generation) return;
    state.connectionError = true;
    showError(error.name === "AbortError" ? "The audit API did not respond in time. Retrying shortly." : error);
    render();
  } finally {
    clearTimeout(timeout);
    if (currentGeneration === generation && !state.feedPaused) pollTimer = setTimeout(poll, state.connectionError ? 7000 : 2000);
  }
}
function humanState(value) { return String(value || "").toLowerCase().replaceAll("_", " "); }
function gateDialog(id) {
  const audit = state.audit, gate = audit.gates.find(g => g.gate_id === id);
  if (!gate) return;
  showDialog("Review human gate", dialogForm(`<div class="dialog-facts"><strong>${esc(gate.title)}</strong><br>${esc(gate.reason)}</div><p class="dialog-copy">${state.preview ? "This records a sample decision in this tab only." : `Your decision applies to revision ${audit.revision} and the current analysis digest. It cannot waive a deterministic policy denial.`}</p><div class="field"><label for="gate-decision">Decision</label><select id="gate-decision" name="decision"><option value="APPROVE">Approve this gate</option><option value="REJECT">Reject this gate</option></select></div><div class="field"><label for="gate-reason">Decision reason</label><textarea id="gate-reason" name="reason" required maxlength="2000" placeholder="What did you verify, or why are you rejecting it?"></textarea></div>${!state.preview && !state.api.officerToken ? '<div class="field"><label for="decision-officer-token">Officer token</label><input id="decision-officer-token" name="officer" type="password" autocomplete="off" required><small>The server validates officer permissions.</small></div>' : ""}`, state.preview ? "Record sample decision" : "Record decision"), "HUMAN REVIEW");
  bindForm(async form => {
    if (state.audit.audit_id !== audit.audit_id) throw new Error("The selected audit changed. Close this dialog and review the current audit.");
    const decision = String(form.get("decision")), reason = String(form.get("reason")).trim();
    if (!reason) throw new Error("Enter a reason for this decision.");
    if (state.preview) {
      Object.assign(gate, { status: decision === "APPROVE" ? "APPROVED" : "REJECTED", decision_reason: reason, actor_id: "Sample officer", decided_at: new Date().toISOString() });
      audit.revision++;
      state.events.push({ sequence: state.events.length + 1, event_type: "HUMAN_GATE_DECIDED", actor_id: "Sample officer", occurred_at: new Date().toISOString(), payload: { reason } });
      if (id === "final-signoff") { audit.state = "FINALIZED"; state.reports.push({ version: 2, kind: "REVIEWED_FINAL", sample: true, available: false, verified: false, published_at: new Date().toISOString() }); }
    } else {
      if (form.get("officer")) state.api.officerToken = String(form.get("officer")).trim();
      state.audit = await state.api.request(`/api/audits/${encodeURIComponent(audit.audit_id)}/gates/${encodeURIComponent(id)}/decision`, { method: "POST", officer: true, body: { decision, reason, expected_revision: audit.revision, analysis_digest: audit.analysis_digest } });
    }
    closeDialog(); render(true); toast(state.preview ? "Sample decision recorded" : "Officer decision recorded");
    if (!state.preview) poll();
  });
}
function referenceDialog() {
  showDialog("Add a Sepolia reference", dialogForm(`<p class="dialog-copy">Attach a transaction hash, contract address, or Sepolia Etherscan link for inspection. This local reference does not change the audit or prove a transaction succeeded.</p><div class="field"><label for="sepolia-reference">Transaction or address</label><input id="sepolia-reference" name="reference" type="text" required spellcheck="false" autocomplete="off" placeholder="0x… or https://sepolia.etherscan.io/…" value="${esc(state.chainReference?.url || "")}"></div>`, "Attach reference"));
  bindForm(async form => { const reference = sepoliaReference(form.get("reference")); if (!reference) throw new Error("Enter a valid Sepolia transaction hash, address, or sepolia.etherscan.io link."); state.chainReference = reference; closeDialog(); render(true); toast("Reference attached locally"); });
}
async function downloadReport(version) {
  try {
    if (state.preview) {
      // Always download the fixed sample draft, not a fabricated reviewed-final report.
      const response = await fetch("/assets/sample-audit.pdf"); if (!response.ok) throw new Error("The sample PDF is unavailable.");
      downloadBlob(await response.blob(), "chainlex-sample-draft.pdf");
      if (Number(version) !== 1) toast("Downloaded the illustrative sample draft. Connect to generate a reviewed final PDF.");
    } else {
      const blob = await state.api.request(`/api/audits/${encodeURIComponent(state.audit.audit_id)}/reports/${Number(version)}.pdf`, { blob: true });
      downloadBlob(blob, `chainlex-${state.audit.audit_id}-v${Number(version)}.pdf`);
    }
  } catch (error) { showError(error); }
}
async function exportAudit() {
  try { const payload = state.preview ? { sample: true, audit: state.audit, events: state.events, reports: state.reports } : await state.api.request(`/api/audits/${encodeURIComponent(state.audit.audit_id)}/export`); downloadBlob(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }), `chainlex-${state.audit.audit_id}.json`); }
  catch (error) { showError(error); }
}
async function loadTransactionConfig() {
  if (!state.api) return;
  try { state.transactionConfig = await state.api.request("/api/transactions/config"); if (viewName() === "transactions") render(true); }
  catch { state.transactionConfig = null; }
}
async function submitTransaction(form) {
  const errorEl = $("#transaction-error"); errorEl.hidden = true;
  const { verification_scenario, ...values } = Object.fromEntries(new FormData(form));
  if (state.preview) { state.transaction = { ...values, preview: true, state: "PREVIEW" }; $("#transaction-result").innerHTML = transactionResult(state); toast("Request previewed. No transaction was sent."); return; }
  const button = form.querySelector('[type="submit"]'); button.disabled = true; state.transactionBusy = true;
  const originalLabel = button.innerHTML; button.innerHTML = '<span class="spinner"></span>Preparing request…';
  const key = form.dataset.requestKey || crypto.randomUUID(); form.dataset.requestKey = key;
  try {
    state.transaction = await state.api.request("/api/transactions", { method: "POST", officer: true, body: { ...values, idempotency_key: key } });
    $("#transaction-result").innerHTML = transactionResult(state); toast("Signed request saved. Tracking the Sepolia receipt."); pollTransaction();
  } catch (error) { errorEl.textContent = error.message; errorEl.hidden = false; }
  finally { state.transactionBusy = false; button.disabled = false; button.innerHTML = originalLabel; }
}
async function pollTransaction() {
  clearTimeout(transactionTimer);
  const tx = state.transaction, api = state.api;
  if (!api || tx?.preview || !tx?.transaction_id || ["CONFIRMED", "REVERTED"].includes(tx.state)) return;
  try { const result = await api.request(`/api/transactions/${encodeURIComponent(tx.transaction_id)}`); if (state.transaction?.transaction_id !== tx.transaction_id || api !== state.api) return; state.transaction = result; if (viewName() === "transactions") $("#transaction-result").innerHTML = transactionResult(state); }
  catch (error) { showError(error); }
  if (api === state.api) transactionTimer = setTimeout(pollTransaction, 5000);
}
async function transactionAudit() {
  try {
    const tx = state.transaction;
    const result = tx.audit_id ? tx : await state.api.request(`/api/transactions/${encodeURIComponent(tx.transaction_id)}/audit`, { method: "POST", officer: true, body: {} });
    state.transaction = { ...tx, audit_id: result.audit_id };
    await openAudit(result.audit_id);
    if (tx.tx_hash) state.chainReference = sepoliaReference(tx.tx_hash);
    render(true);
  } catch (error) { showError(error); }
}

document.addEventListener("click", event => {
  const button = event.target.closest("button, [data-action]"); if (!button || button.disabled) return;
  if (["connect-sidebar", "connect-banner"].includes(button.id)) connectDialog();
  else if (button.id === "new-audit" || button.dataset.action === "new") newAuditDialog();
  else if (button.id === "open-audit") openAuditDialog();
  else if (button.id === "close-dialog" || button.dataset.action === "cancel") closeDialog();
  else if (button.dataset.agent) { state.agent = button.dataset.agent; render(true); }
  else if (button.dataset.gate) gateDialog(button.dataset.gate);
  else if (button.dataset.download) downloadReport(button.dataset.download);
  else if (button.dataset.action === "reference") referenceDialog();
  else if (button.dataset.action === "connect") connectDialog();
  else if (button.dataset.action === "export") exportAudit();
  else if (button.dataset.action === "disconnect") disconnect();
  else if (button.dataset.action === "transaction-audit") transactionAudit();
  else if (button.dataset.action === "verify-request") verifyRequest(button);
  else if (button.dataset.action === "feed") { state.feedPaused = !state.feedPaused; if (state.feedPaused) resetRequest(); else poll(); render(true); }
  else if (button.dataset.action === "refresh") { clearError(); if (state.api && state.audit) poll(); else connectDialog(); }
  else if (button.id === "theme-toggle") { const dark = document.documentElement.dataset.theme !== "dark"; setTheme(dark ? "dark" : "light"); try { localStorage.setItem("chainlex-theme", dark ? "dark" : "light"); } catch { /* Storage may be disabled. */ } }
});
document.addEventListener("keydown", event => {
  if (!event.target.matches("[data-agent]") || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault(); const index = AGENTS.findIndex(a => a.id === state.agent);
  const next = event.key === "Home" ? 0 : event.key === "End" ? AGENTS.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + AGENTS.length) % AGENTS.length;
  state.agent = AGENTS[next].id; render(true); document.querySelector(`[data-agent="${state.agent}"]`).focus();
});
document.addEventListener("input", event => {
  if (event.target.id === "event-filter") { state.eventFilter = event.target.value; const value = state.eventFilter.toLowerCase(); const filtered = state.events.filter(e => `${e.event_type} ${e.actor_id} ${e.event_type.replaceAll("_", " ")}`.toLowerCase().includes(value)); $("#full-event-list").innerHTML = eventRows([...filtered].reverse()) || '<li><p class="text-note">No matching events.</p></li>'; }
  if (event.target.closest("#transaction-form")) {
    delete event.target.closest("form").dataset.requestKey;
    state.verification = null;
    if ($("#verification-result")) $("#verification-result").innerHTML = "";
  }
});
document.addEventListener("submit", event => { if (event.target.id === "transaction-form") { event.preventDefault(); submitTransaction(event.target); } });
$("#action-dialog").addEventListener("close", () => { $("#dialog-content").innerHTML = ""; returnFocus?.focus({ preventScroll: true }); });
$("#action-dialog").addEventListener("click", event => { const box = event.currentTarget.getBoundingClientRect(); if (event.target === event.currentTarget && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) closeDialog(); });
window.addEventListener("hashchange", () => { render(true); $("#main").focus({ preventScroll: true }); if (viewName() === "transactions") loadTransactionConfig(); });
document.addEventListener("visibilitychange", () => { if (document.hidden) resetRequest(); else { poll(); pollTransaction(); } });
function setTheme(theme) { document.documentElement.dataset.theme = theme; const button = $("#theme-toggle"); button.innerHTML = icon(theme === "dark" ? "sun" : "moon"); button.setAttribute("aria-label", `Switch to ${theme === "dark" ? "light" : "dark"} theme`); }
fillIcons();
try { setTheme(localStorage.getItem("chainlex-theme") === "dark" ? "dark" : "light"); } catch { setTheme("light"); }
render(true);
if (new URL(location.href).searchParams.has("audit")) { toast("Reconnect to restore the linked audit."); }

async function verifyRequest(button) {
  if (!state.api) { connectDialog(); return; }
  const form = $("#transaction-form");
  if (!form.reportValidity()) return;
  button.disabled = true;
  button.innerHTML = '<span class="spinner"></span>Checking…';
  const payload = verificationPayload(form, state.transactionConfig?.signer);
  try {
    const result = await state.api.request("/api/compliance/verify", { method: "POST", body: payload });
    const current = $("#transaction-form");
    if (!current || JSON.stringify(verificationPayload(current, state.transactionConfig?.signer)) !== JSON.stringify(payload)) { toast("Inputs changed. Run preflight again for the current request."); return; }
    state.verification = result;
    if ($("#verification-result")) $("#verification-result").innerHTML = verificationView(state.verification);
    toast("Simulated preflight complete. No Sepolia transaction was submitted.");
  } catch (error) { showError(error); }
  finally { button.disabled = false; button.innerHTML = "Run preflight"; }
}
