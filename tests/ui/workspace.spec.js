import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const recipients = ["0x2222222222222222222222222222222222222222", "0x57cb113ffba59eb1965bb7ee0b9dfba7ff291a4f"];

test("transaction page replaces the audit workspace and exposes only the requested choices", async ({ page }) => {
  await page.goto("/#workspace");
  await expect(page.getByRole("heading", { name: "Create transaction", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Audit workspace", exact: true })).toHaveCount(0);
  await expect(page.locator("[data-preset]")).toHaveCount(0);
  await expect(page.getByText("Choose Test Case", { exact: true })).toHaveCount(0);
  await expect(page.locator("#txn-beneficiary option")).toHaveText(recipients);
  await expect(page.locator("#verification-scenario option")).toHaveCount(1);
  for (const recipient of recipients) {
    await page.getByLabel("Beneficiary address").selectOption(recipient);
    await expect(page.locator("#node-dest-addr")).toHaveText(recipient);
    await expect(page.getByLabel("Beneficiary address")).toHaveValue(recipient);
  }
});

test("preview sends no transaction and records an explicit preview log", async ({ page }) => {
  let submissions = 0;
  await page.route("**/api/transactions", route => { submissions++; return route.abort(); });
  await page.goto("/");
  await page.getByLabel("Beneficiary address").selectOption(recipients[1]);
  await page.getByRole("button", { name: "Preview request", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Request preview", exact: true })).toBeVisible();
  await expect(page.locator("[data-execution-logs]")).toContainText("No transaction was sent");
  await page.getByRole("link", { name: "Logs", exact: true }).click();
  await expect(page.locator("[data-execution-logs]")).toContainText("No transaction was sent");
  await page.getByRole("button", { name: "Clear logs" }).click();
  await expect(page.locator("[data-execution-logs]")).toContainText("No activity yet");
  expect(submissions).toBe(0);
});

test("failed authentication appears in logs without exposing credentials", async ({ page }) => {
  await page.route("**/api/audits/scenarios", route => route.fulfill({ status: 401, json: { detail: "Invalid token" } }));
  await page.goto("/");
  await page.locator("#connect-banner").click();
  await page.getByLabel("Workspace access token").fill("private-analyst-token");
  await page.locator('#dialog-form button[type="submit"]').click();
  await expect(page.locator("#form-error")).toContainText("Invalid token");
  await page.getByRole("button", { name: "Close dialog" }).click();
  await expect(page.locator("[data-execution-logs]")).toContainText("HTTP 401");
  await expect(page.locator("[data-execution-logs]")).not.toContainText("private-analyst-token");
  await expect(page.locator("#mode-banner")).toContainText("Preview workspace");
});

test("preflight receives the selected recipient and logs its result", async ({ page }) => {
  await page.route("**/api/compliance/verify", async route => {
    const body = route.request().postDataJSON();
    expect(body.scenario).toBe("custom");
    expect(body.beneficiary_address).toBe(recipients[1]);
    return route.fulfill({ json: { mode: "simulated", overall_status: "PASS", legs: {} } });
  });
  await page.goto("/");
  await page.getByLabel("Beneficiary address").selectOption(recipients[1]);
  await page.getByRole("button", { name: "Run Preflight", exact: true }).click();
  await expect(page.locator("[data-execution-logs]")).toContainText("Preflight result: PASS");
  await expect(page.locator("#verification-result")).toContainText("Pass");
});

for (const theme of ["light", "dark"]) {
  test(`transaction page and logs are accessible and responsive in ${theme} mode`, async ({ page }) => {
    await page.goto("/");
    if (theme === "dark") await page.getByRole("button", { name: "Switch to dark theme" }).click();
    await page.emulateMedia({ reducedMotion: "reduce" });
    for (const view of ["transactions", "logs"]) {
      await page.goto(`/#${view}`);
      for (const width of [375, 768, 1440]) {
        await page.setViewportSize({ width, height: 1000 });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      }
      const audit = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
      expect(audit.violations).toEqual([]);
    }
  });
}
