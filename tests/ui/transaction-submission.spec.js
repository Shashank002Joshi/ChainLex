import { test, expect } from "@playwright/test";

for (const fail of [false, true]) {
  test(`submission uses real API and ${fail ? "surfaces errors" : "waits for receipt"}`, async ({ page }) => {
    const hash = "0x" + "ab".repeat(32);
    let submissions = 0, confirmed = false;
    await page.route("**/api/**", async route => {
      const request = route.request(), path = new URL(request.url()).pathname;
      if (path === "/api/audits/scenarios") return route.fulfill({ json: { scenarios: {} } });
      if (path === "/api/transactions/config") return route.fulfill({ json: { configured: true, signer: "0x" + "11".repeat(20) } });
      if (path === "/api/transactions") {
        submissions++;
        expect(request.headers().authorization).toBe("Bearer officer-test");
        expect(request.postDataJSON().idempotency_key).toBeTruthy();
        expect(request.postDataJSON().verification_mode).toBeUndefined();
        expect(request.postDataJSON().beneficiary).toBe(fail ? "0x57cb113ffba59eb1965bb7ee0b9dfba7ff291a4f" : "0x2222222222222222222222222222222222222222");
        if (fail) return route.fulfill({ status: 503, json: { detail: "RPC unavailable" } });
        return route.fulfill({ status: 202, json: { transaction_id: "real-request", state: "SUBMITTED", tx_hash: hash } });
      }
      if (path === "/api/transactions/real-request") return route.fulfill({ json: { transaction_id: "real-request", state: confirmed ? "CONFIRMED" : "SUBMITTED", tx_hash: hash, ...(confirmed ? { block_number: 123 } : {}) } });
      return route.fulfill({ status: 500, json: { detail: "Unexpected API request" } });
    });
    await page.goto("/#transactions");
    await page.locator("#connect-banner").click();
    await page.locator("#access-token").fill("analyst-test");
    await page.locator("#officer-token").fill("officer-test");
    await page.locator('#dialog-form button[type="submit"]').click();
    await expect(page.locator("#mode-banner")).toContainText("Connected workspace");
    if (fail) await page.getByLabel("Beneficiary address").selectOption("0x57cb113ffba59eb1965bb7ee0b9dfba7ff291a4f");
    await page.locator('#transaction-form button[type="submit"]').click();
    if (fail) {
      await expect(page.locator("#transaction-error")).toContainText("RPC unavailable");
      await expect(page.locator("#transaction-result")).toContainText("RPC unavailable");
      await expect(page.locator("[data-execution-logs]")).toContainText("RPC unavailable");
      await expect(page.locator("#transaction-result a[href*='etherscan']")).toHaveCount(0);
    } else {
      await expect(page.locator("#transaction-result")).toContainText("Submitted");
      await expect(page.locator("[data-demo-stage]")).not.toHaveText(["Finished", "Finished", "Finished"]);
      await expect(page.locator("#transaction-result")).not.toContainText("Receipt block");
      await expect(page.locator("#transaction-result a[href*='etherscan']")).toHaveAttribute("href", `https://sepolia.etherscan.io/tx/${hash}`);
      confirmed = true;
      await expect(page.locator("#transaction-result")).toContainText("Confirmed", { timeout: 12000 });
      await expect(page.locator("#transaction-result")).toContainText("#123");
      await expect(page.locator("[data-execution-logs]")).toContainText("CONFIRMED · block 123");
    }
    expect(submissions).toBe(1);
    await expect(page.locator('[data-action="verify-request"]')).toBeEnabled({ timeout: 10000 });
    await expect(page.locator("[data-execution-logs]")).not.toContainText("officer-test");
  });
}

test("missing officer token explains the issue and opens connection settings without submitting", async ({ page }) => {
  let submissions = 0;
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/audits/scenarios") return route.fulfill({ json: { scenarios: {} } });
    if (path === "/api/transactions/config") return route.fulfill({ json: { configured: true } });
    submissions++;
    return route.fulfill({ status: 500, json: {} });
  });
  await page.goto("/");
  await page.locator("#connect-banner").click();
  await page.locator("#access-token").fill("analyst-only");
  await page.locator('#dialog-form button[type="submit"]').click();
  await expect(page.locator("#mode-banner")).toContainText("Connected workspace");
  await page.locator('#transaction-form button[type="submit"]').click();
  await expect(page.locator("#transaction-result")).toContainText("An officer token is required");
  await expect(page.locator("#action-dialog")).toBeVisible();
  expect(submissions).toBe(0);
});

test("broadcast rejection is shown even when the signed request was saved", async ({ page }) => {
  const tx = { transaction_id: "uncertain-request", state: "SUBMISSION_UNKNOWN", tx_hash: "0x" + "ab".repeat(32), submission_error: "Sepolia eth_sendRawTransaction rejected the request: nonce too low" };
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/audits/scenarios") return route.fulfill({ json: { scenarios: {} } });
    if (path === "/api/transactions/config") return route.fulfill({ json: { configured: true } });
    return route.fulfill({ status: path === "/api/transactions" ? 202 : 200, json: tx });
  });
  await page.goto("/");
  await page.locator("#connect-banner").click();
  await page.locator("#access-token").fill("analyst-test");
  await page.locator("#officer-token").fill("officer-test");
  await page.locator('#dialog-form button[type="submit"]').click();
  await expect(page.locator("#mode-banner")).toContainText("Connected workspace");
  await page.locator('#transaction-form button[type="submit"]').click();
  await expect(page.locator("#transaction-result [role=alert]")).toContainText("nonce too low");
  await expect(page.locator("#transaction-result")).not.toContainText("successful receipt");
  await expect(page.locator("[data-execution-logs]")).toContainText("nonce too low");
});
