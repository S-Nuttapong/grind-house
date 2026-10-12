import { expect, test } from "@playwright/test";

test("create a search, toggle a source, and queue a run", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/searches");
  await page.getByRole("button", { name: "New search" }).click();
  await page.getByLabel("Name").fill("UAT software");
  const linkedin = page.getByRole("switch", { name: "Linkedin Guest enabled" });
  await linkedin.click();
  await linkedin.click();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("cell", { name: "UAT software" })).toBeVisible();
  const row = page.getByRole("row").filter({ hasText: "UAT software" });
  await row.getByRole("button", { name: "Sources" }).click();
  await page.getByRole("button", { name: "Run now" }).first().click();
  await page.goto("/runs");
  await expect(page.getByRole("row", { name: /UAT software|Linkedin Guest/ }).first()).toBeVisible({
    timeout: 90_000,
  });
});
