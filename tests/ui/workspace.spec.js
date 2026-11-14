import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { previewState } from "../../src/chainlex/api/static/workspace-preview.js";

test("preview exposes all three outputs, safe references, and a real sample PDF", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("tab")).toHaveCount(3);
  await expect(page.locator(".case-title h2")).toHaveText("Canada Singapore");
  await page.getByRole("tab", { name: /Governed memory/ }).click();
  await expect(page.getByRole("heading", { name: "Memory influence" })).toBeVisible();
  await page.getByRole("tab", { name: /Durable completion/ }).click();
  await expect(page.getByRole("heading", { name: "Durable workflow" })).toBeVisible();
  const tab = page.getByRole("tab", { name: /Durable completion/ });
  await tab.press("Home");
  await expect(page.getByRole("tab", { name: /Authority & audit/ })).toBeFocused();
  await page.getByRole("button", { name: "Add Sepolia reference" }).click();
  await page.getByLabel("Transaction or address").fill("javascript:alert(1)");
  await page.getByRole("button", { name: "Attach reference" }).click();
  await expect(page.locator("#form-error")).toContainText("valid Sepolia");
  const hash = "0x" + "ab".repeat(32);
  await page.getByLabel("Transaction or address").fill(hash);
  await page.getByRole("button", { name: "Attach reference" }).click();
  await expect(page.getByRole("link", { name: /Sepolia transaction/ })).toHaveAttribute("href", `https://sepolia.etherscan.io/tx/${hash}`);
  const pendingDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download example PDF" }).click();
  expect((await pendingDownload).suggestedFilename()).toBe("chainlex-sample-draft.pdf");
});

test("sample human gates enforce ordering and collect a decision reason", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator('[data-gate="final-signoff"]')).toBeDisabled();
  for (const gate of ["evidence-review", "corridor-verification", "final-signoff"]) {
    await page.locator(`[data-gate="${gate}"]`).click();
    await page.getByLabel("Decision reason").fill("Reviewed this illustrative sample evidence.");
    await page.getByRole("button", { name: "Record sample decision" }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible();
  }
  await expect(page.locator(".gates-header")).toContainText("0 pending");
  await expect(page.getByRole("button", { name: "Connect for a final PDF" })).toBeVisible();
});

test("transaction preview has no wallet flow and sends no requests", async ({ page }) => {
  let submissions = 0;
  await page.route("**/api/transactions", route => { submissions++; return route.abort(); });
  await page.goto("/#transactions");
  await expect(page.getByRole("heading", { name: "Create transaction", exact: true })).toBeVisible();
  await expect(page.getByText("Backend service key", { exact: true })).toBeVisible();
  await page.getByLabel("Amount (USDC)").fill("250000.000001");
  await page.getByRole("button", { name: "Preview request" }).click();
  await expect(page.getByRole("heading", { name: "Request preview" })).toBeVisible();
  await expect(page.locator("#transaction-result")).toContainText("250000.000001");
  expect(submissions).toBe(0);
});

test("connected workflow polls real API contracts, submits version-bound decisions, downloads final", async ({ page }) => {
  const sample = previewState();
  const audit = { ...sample.audit, audit_id: "audit-test", tenant_id: "bank_a" };
  let reports = [{ version: 1, kind: "DRAFT", verified: true, sha256: "a".repeat(64), published_at: audit.created_at }];
  const decisions = [];
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (path === "/api/audits/scenarios") return route.fulfill({ json: { scenarios: { corridor_audit: "Compare corridors" } } });
    if (path === "/api/transactions/config") return route.fulfill({ json: { configured: false } });
    if (path === "/api/audits" || path === "/api/audits/audit-test") return route.fulfill({ json: audit, status: path === "/api/audits" ? 202 : 200 });
    if (path.endsWith("/events")) return route.fulfill({ json: sample.events });
    if (path.endsWith("/reports")) return route.fulfill({ json: reports });
    if (path.endsWith(".pdf")) return route.fulfill({ contentType: "application/pdf", body: "%PDF-1.4\nMock transport document" });
    if (path.includes("/gates/")) {
      const body = request.postDataJSON();
      expect(request.headers().authorization).toBe("Bearer officer-test");
      expect(body.expected_revision).toBe(audit.revision);
      expect(body.analysis_digest).toBe(audit.analysis_digest);
      const gate = audit.gates.find(g => path.includes(`/gates/${g.gate_id}/`));
      gate.status = "APPROVED"; gate.decision_reason = body.reason; decisions.push(gate.gate_id); audit.revision++;
      if (gate.gate_id === "final-signoff") { audit.state = "FINALIZED"; reports = [...reports, { version: 2, kind: "REVIEWED_FINAL", verified: true, published_at: audit.created_at }]; }
      return route.fulfill({ json: audit });
    }
    return route.fulfill({ status: 404, json: { detail: "Not found" } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: /Connect workspace/ }).click();
  await page.getByLabel("Workspace access token").fill("analyst-test");
  await page.getByLabel("Officer token", { exact: false }).fill("officer-test");
  await page.getByRole("dialog").getByRole("button", { name: "Connect workspace", exact: true }).click();
  await page.getByRole("button", { name: "New audit" }).click();
  await page.getByRole("button", { name: "Start audit", exact: true }).click();
  await expect(page.locator(".activity-status")).toContainText("Live");
  await expect(page.locator(".gates-header")).toContainText("3 pending");
  for (const gate of ["evidence-review", "corridor-verification", "final-signoff"]) {
    await page.locator(`[data-gate="${gate}"]`).click();
    await page.getByLabel("Decision reason").fill("Verified the current immutable analysis and source status.");
    await page.getByRole("button", { name: "Record decision", exact: true }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible();
  }
  await expect(page.locator(".paper-bottom")).toContainText("Version 2");
  expect(decisions).toEqual(["evidence-review", "corridor-verification", "final-signoff"]);
  const storage = await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }));
  expect(storage).not.toContain("analyst-test"); expect(storage).not.toContain("officer-test");
});

test("failed connection is actionable and never turns a preview into live data", async ({ page }) => {
  await page.route("**/api/audits/scenarios", route => route.fulfill({ status: 401, json: { detail: "Invalid token" } }));
  await page.goto("/");
  await page.getByRole("button", { name: /Connect workspace/ }).click();
  await page.getByLabel("Workspace access token").fill("invalid");
  await page.getByRole("dialog").getByRole("button", { name: "Connect workspace", exact: true }).click();
  await expect(page.locator("#form-error")).toContainText("Invalid token");
  await page.getByRole("button", { name: "Close dialog" }).click();
  await expect(page.locator(".activity-status")).toContainText("Sample events");
});

test("transaction preflight renders the latest backend court and six-leg result", async ({ page }) => {
  await page.route("**/api/audits/scenarios", route => route.fulfill({ json: { scenarios: { corridor_audit: "Corridor audit" } } }));
  await page.route("**/api/transactions/config", route => route.fulfill({ json: { configured: true, signer: "0x9999999999999999999999999999999999999999" } }));
  await page.goto("/#transactions");
  await page.getByRole("button", { name: "Run preflight" }).click();
  await page.getByLabel("Workspace access token").fill("preflight-test");
  await page.getByRole("dialog").getByRole("button", { name: "Connect workspace", exact: true }).click();
  const standard = page.waitForRequest(r => r.url().endsWith("/api/compliance/verify"));
  await page.getByRole("button", { name: "Run preflight" }).click();
  const standardPayload = (await standard).postDataJSON();
  expect(standardPayload.initiator_address).toBe("0x1111111111111111111111111111111111111111");
  await expect(page.locator("#verification-result .panel-head .badge")).toHaveText("Pass");
  await page.getByLabel("Preflight scenario").selectOption("sanctions_blocked");
  const request = page.waitForRequest(r => r.url().endsWith("/api/compliance/verify"));
  await page.getByRole("button", { name: "Run preflight" }).click();
  expect((await request).postDataJSON().mode).toBe("simulated");
  await expect(page.getByRole("heading", { name: "Regulatory prosecutor", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Defense counsel", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Chief compliance officer", exact: true })).toBeVisible();
  await expect(page.locator("#verification-result .panel-head")).toContainText("Deny");
  await page.getByText("Completed preflight trace", { exact: true }).click();
  await expect(page.locator("#verification-result")).toContainText("FINALIZING -> FINALIZED");
});

for (const theme of ["light", "dark"]) {
  test(`responsive and accessible in ${theme} mode`, async ({ page }) => {
    await page.goto("/");
    if (theme === "dark") await page.getByRole("button", { name: "Switch to dark theme" }).click();
    await page.emulateMedia({ reducedMotion: "reduce" });
    const audit = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    expect(audit.violations).toEqual([]);
    for (const viewport of [{ width: 375, height: 812 }, { width: 812, height: 375 }, { width: 768, height: 1024 }]) {
      await page.setViewportSize(viewport);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await expect(page.getByRole("tab", { name: /Authority & audit/ })).toBeVisible();
    }
  });
}
