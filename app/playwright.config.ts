import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 360_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: process.env.UAT_BASE_URL ?? "http://127.0.0.1:3000",
    trace: "retain-on-failure",
  },
});
