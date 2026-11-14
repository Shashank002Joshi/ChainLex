export const AGENTS = [
  { id: "auditable_action", number: "01", icon: "shield", name: "Authority & audit", fullName: "Auditable Action Agent", statement: "Agents you can audit" },
  { id: "governed_memory", number: "02", icon: "memory", name: "Governed memory", fullName: "Governed Memory Agent", statement: "Memory you can govern" },
  { id: "durable_completion", number: "03", icon: "cycle", name: "Durable completion", fullName: "Durable Completion Agent", statement: "Finish the job" },
];
const paths = {
  layers: '<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5M3 16l9 5 9-5"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6Z"/><path d="M14 2v6h6M8 13h8M8 17h5"/>',
  activity: '<path d="M2 12h5l3-8 4 16 3-8h5"/>',
  code: '<path d="m8 7-5 5 5 5m8-10 5 5-5 5m-3-14-2 18"/>',
  external: '<path d="M14 3h7v7m0-7L10 14"/><path d="M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5"/>',
  plug: '<path d="m12 22 3-3v-3M8 3v5m8-5v5M6 8h12v4a6 6 0 0 1-12 0V8Z"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>', arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
  moon: '<path d="M21 13a9 9 0 1 1-10-10 7 7 0 0 0 10 10Z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  plus: '<path d="M12 4v16M4 12h16"/>', close: '<path d="m6 6 12 12M6 18 18 6"/>',
  shield: '<path d="M12 3 3 7v5c0 5 9 10 9 10s9-5 9-10V7l-9-4Z"/><path d="m8 12 3 3 5-6"/>',
  memory: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
  cycle: '<path d="M20 7V3l-4 4m4 0a9 9 0 0 0-15 3M4 17v4l4-4m-4 0a9 9 0 0 0 15-3"/>',
  check: '<path d="m5 12 4 4L19 6"/>', circle: '<circle cx="12" cy="12" r="8"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
  route: '<circle cx="5" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><path d="M7 5h8a4 4 0 0 1 0 8H9a4 4 0 0 0 0 6h8"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  pause: '<path d="M8 5v14M16 5v14"/>', play: '<path d="m8 4 12 8-12 8V4Z"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.1"/>',
  send: '<path d="m22 2-7 20-4-9-9-4 20-7ZM22 2 11 13"/>',
  copy: '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
};
export const icon = (name) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.circle}</svg>`;
export function fillIcons(root = document) { root.querySelectorAll("[data-icon]").forEach(el => { el.innerHTML = icon(el.dataset.icon); }); }
export const esc = (value = "") => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
export const humanize = value => String(value || "").toLowerCase().replace(/_/g, " ").replace(/^./, c => c.toUpperCase());
export const bankName = id => ({ scotiabank: "Scotiabank", jpmorgan_chase: "JPMorgan Chase", dbs: "DBS" })[id] || humanize(id);
export const countryName = id => ({ CA: "Canada", US: "United States", SG: "Singapore" })[id] || id;
export function timeLabel(value) { const date = new Date(value); return Number.isNaN(date.valueOf()) ? "—" : new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(date); }
export function dateLabel(value) { const date = new Date(value); return Number.isNaN(date.valueOf()) ? "—" : new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" }).format(date); }
export function safeUrl(value) { try { const url = new URL(value); return url.protocol === "https:" && !url.username && !url.password ? url.href : null; } catch { return null; } }
export function sepoliaReference(value) {
  const raw = String(value || "").trim();
  if (/^0x[0-9a-fA-F]{64}$/.test(raw)) return { url: `https://sepolia.etherscan.io/tx/${raw}`, hash: raw, kind: "transaction" };
  if (/^0x[0-9a-fA-F]{40}$/.test(raw)) return { url: `https://sepolia.etherscan.io/address/${raw}`, hash: raw, kind: "address" };
  try {
    const url = new URL(raw);
    if (url.protocol !== "https:" || url.hostname !== "sepolia.etherscan.io" || url.port || url.username || url.password) return null;
    const match = url.pathname.match(/^\/(tx|address)\/(0x[0-9a-fA-F]+)\/?$/);
    if (match && match[2].length === (match[1] === "tx" ? 66 : 42)) return sepoliaReference(match[2]);
  } catch { /* Unrecognized reference. */ }
  return null;
}
export class ApiError extends Error { constructor(message, status) { super(message); this.status = status; } }
export class WorkspaceApi {
  constructor(token, officerToken = "") { this.token = token; this.officerToken = officerToken; }
  async request(path, { method = "GET", body, signal, officer = false, blob = false } = {}) {
    let response;
    try {
      response = await fetch(path, { method, signal, headers: { Authorization: `Bearer ${officer ? this.officerToken || this.token : this.token}`, ...(body ? { "Content-Type": "application/json" } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}) });
    } catch (error) { if (error.name === "AbortError") throw error; throw new ApiError("Connection lost. Check that the API is running, then retry.", 0); }
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      const detail = data.detail;
      const messages = { 401: "The access token was not accepted. Reconnect with a valid token.", 403: "This action requires an authorized officer token.", 404: "This audit or API endpoint is unavailable. Check the audit ID and backend version.", 409: "The audit changed while you were reviewing it. Refresh and review the latest version.", 503: "A required service is unavailable. Check the API and database, then retry." };
      throw new ApiError(typeof detail?.message === "string" ? detail.message : typeof detail === "string" ? detail : messages[response.status] || "The request could not be completed. Please retry.", response.status);
    }
    return blob ? response.blob() : response.json();
  }
}
export const SCENARIOS = {
  corridor_audit: "Compare Canada-to-Singapore corridors",
  memory_influence: "See how governed memory changes a decision",
  no_suitable_route: "Review a case with no suitable route",
  schema_change: "Recover from a supported source change",
  unsupported_schema: "Escalate an unsupported source change",
};
