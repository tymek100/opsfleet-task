import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  timeout: 30000,
  use: {
    baseURL: "http://127.0.0.1:8765",
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: ".venv/bin/python -m tests.support.gui_preview",
    cwd: "..",
    url: "http://127.0.0.1:8765/health",
    reuseExistingServer: false,
    timeout: 30000,
  },
});
