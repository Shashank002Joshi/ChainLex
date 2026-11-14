import { esc, icon } from "./workspace-core.js";

export function logRows(logs) {
  if (!logs.length) return '<li class="text-note">No activity yet. Connect the workspace or run a transaction to see logs.</li>';
  return [...logs].reverse().map(entry => `<li class="execution-log ${esc(entry.level)}"><time datetime="${esc(entry.time)}">${esc(new Date(entry.time).toLocaleTimeString())}</time><strong>${esc(entry.level.toUpperCase())}</strong><span>${esc(entry.message)}${entry.count > 1 ? ` (×${entry.count})` : ""}</span></li>`).join("");
}

export function logsPanel(logs, compact = false) {
  return `<section class="panel execution-logs${compact ? " compact" : ""}" aria-label="Execution logs"><div class="panel-head"><h2>${icon("activity")}Execution logs</h2><button type="button" class="text-button" data-action="clear-logs">Clear logs</button></div><p class="text-note panel-padding">Activity from this browser session. Logs clear on reload; access tokens and private keys are excluded.</p><ol class="execution-log-list" data-execution-logs aria-live="polite" aria-relevant="additions text">${logRows(logs)}</ol></section>`;
}
