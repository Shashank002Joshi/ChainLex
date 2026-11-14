import assert from "node:assert/strict";
import { test } from "node:test";
import { esc, safeUrl, sepoliaReference, WorkspaceApi } from "../../src/chainlex/api/static/workspace-core.js";
import { verificationView } from "../../src/chainlex/api/static/workspace-verification.js";

test("simulated or failed dispatch cannot display a confirmed explorer link", () => {
  const dispatch = { status: "CONFIRMED", tx_hash: "0x" + "ab".repeat(32) };
  for (const result of [
    { mode: "simulated", overall_status: "BLOCK", legs: { leg_5_dispatch: dispatch } },
    { mode: "sepolia", overall_status: "BLOCK", legs: { leg_5_dispatch: { ...dispatch, status: "FAILED", error: "RPC unavailable" } } },
  ]) {
    const html = verificationView(result);
    assert.equal(html.includes('href="https://sepolia.etherscan.io/tx/'), false);
    assert.equal(html.includes("Protective On-Chain Hold Dispatched"), false);
  }
});

test("only Sepolia explorer references produce transaction links", () => {
  const hash = "0x" + "ab".repeat(32);
  assert.equal(sepoliaReference(hash).url, `https://sepolia.etherscan.io/tx/${hash}`);
  assert.equal(sepoliaReference(`https://sepolia.etherscan.io/tx/${hash}?test=1`).hash, hash);
  assert.equal(sepoliaReference("0x" + "ab".repeat(20)).kind, "address");
  for (const url of [`https://etherscan.io/tx/${hash}`, `https://sepolia.etherscan.io.evil.test/tx/${hash}`, `https://evil@sepolia.etherscan.io/tx/${hash}`, `http://sepolia.etherscan.io/tx/${hash}`, "javascript:alert(1)", "0xabc"]) assert.equal(sepoliaReference(url), null);
});
test("untrusted source text is escaped and executable links are rejected", () => {
  assert.equal(esc('<img src=x onerror="alert(1)">'), "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;");
  assert.equal(safeUrl("javascript:alert(1)"), null);
  assert.equal(safeUrl("https://www.mas.gov.sg/regulation"), "https://www.mas.gov.sg/regulation");
});
test("API mutations use the officer credential and structured JSON", async () => {
  const original = globalThis.fetch;
  let call;
  globalThis.fetch = async (path, options) => { call = { path, options }; return new Response('{"accepted":true}', { status: 202, headers: { "Content-Type": "application/json" } }); };
  try {
    await new WorkspaceApi("analyst", "officer").request("/api/transactions", { method: "POST", officer: true, body: { amount: "1.000001" } });
    assert.equal(call.options.headers.Authorization, "Bearer officer");
    assert.deepEqual(JSON.parse(call.options.body), { amount: "1.000001" });
  } finally { globalThis.fetch = original; }
});

test("API validation errors identify the invalid transaction field", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: [{ loc: ["body", "amount"], msg: "Amount must be positive" }] }), { status: 422 });
  try {
    await assert.rejects(new WorkspaceApi("analyst", "officer").request("/api/transactions"), /amount: Amount must be positive/);
  } finally { globalThis.fetch = original; }
});
