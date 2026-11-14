import { test, expect } from "@playwright/test";

test("agent demo shows each stage, logs progress, and sends no API or chain requests", async ({ page }) => {
  const apiRequests = [];
  page.on("request", request => { if (new URL(request.url()).pathname.startsWith("/api/")) apiRequests.push(request.url()); });
  await page.goto("/");
  const cards = page.locator("[data-demo-agent]");
  await expect(cards).toHaveCount(3);
  await expect(page.locator("body")).not.toContainText(/demo/i);
  await page.getByRole("button", { name: "Replay agent animation" }).click();
  await expect(cards.nth(0).locator("[data-demo-stage]")).toHaveText("Starting");
  await expect(page.locator("[data-execution-logs]")).toContainText("Workflow · Regulatory prosecutor: Thinking");
  await expect(page.locator("[data-execution-logs]")).toContainText("Workflow · Regulatory prosecutor: Working");
  await expect(page.locator('[data-action="verify-request"]')).toBeDisabled();
  await expect(cards.locator("[data-demo-stage]")).toHaveText(["Finished", "Finished", "Finished"], { timeout: 10000 });
  await expect(page.locator("[data-execution-logs]")).toContainText("Workflow · Chief compliance officer: Finished");
  await expect(page.getByRole("button", { name: "Replay agent animation" })).toBeEnabled();
  expect(apiRequests).toEqual([]);
  await expect(page.locator("#transaction-result")).toBeEmpty();
});

test("a failed preflight stops the demo and does not show finished agents", async ({ page }) => {
  await page.route("**/api/audits/scenarios", route => route.fulfill({ json: { scenarios: {} } }));
  await page.route("**/api/transactions/config", route => route.fulfill({ json: { configured: true } }));
  await page.route("**/api/compliance/verify", route => route.fulfill({ status: 502, json: { detail: "Preflight service unavailable" } }));
  await page.goto("/");
  await page.locator("#connect-banner").click();
  await page.locator("#access-token").fill("test-analyst");
  await page.locator('#dialog-form button[type="submit"]').click();
  await expect(page.locator("#mode-banner")).toContainText("Connected workspace");
  await page.getByRole("button", { name: "Run Preflight", exact: true }).click();
  await expect(page.locator("[data-demo-stage]")).toHaveText(["Stopped", "Stopped", "Stopped"]);
  await expect(page.locator("#transaction-error")).toContainText("Preflight service unavailable");
  await expect(page.locator("[data-execution-logs]")).toContainText("Workflow stopped");
});
