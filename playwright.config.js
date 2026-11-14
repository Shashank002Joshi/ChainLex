import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/ui",
  testMatch: "**/*.spec.js",
  fullyParallel: true,
  use: { baseURL: "http://127.0.0.1:8012", viewport: { width: 1440, height: 1000 }, trace: "retain-on-failure" },
  webServer: {
    command: "uv run python -m uvicorn chainlex.api.app:create_app --factory --host 127.0.0.1 --port 8012",
    url: "http://127.0.0.1:8012/health/live",
    reuseExistingServer: !process.env.CI,
    timeout: 60000,
  },
});
