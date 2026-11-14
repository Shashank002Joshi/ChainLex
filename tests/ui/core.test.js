import assert from "node:assert/strict";
import { test } from "node:test";
import { esc, safeUrl, sepoliaReference, WorkspaceApi } from "../../src/chainlex/api/static/workspace-core.js";

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
