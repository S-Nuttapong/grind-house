import { expect, test, type Locator, type Page } from "@playwright/test";

test.use({ viewport: { width: 1440, height: 900 }, actionTimeout: 15_000 });

test("multi-select countries and role, then set a minimum score", async ({ page, request }) => {
  let reachable = true;
  try {
    const home = await request.get("/");
    reachable = home.ok();
  } catch {
    reachable = false;
  }
  test.skip(!reachable, "board is not running");

  await page.goto("/");
  const results = page.getByRole("region", { name: "Job results" });
  await expect(results).toBeVisible();
  const starting = await jobCount(results);

  await choose(page, "Country", "United States");
  await expect(page.getByRole("button", { name: "Remove United States" })).toBeVisible();
  await choose(page, "Country", "Canada");
  await expect.poll(() => param(page, "country")).toBe("US,CA");
  await expect.poll(() => jobCount(results)).toBeLessThan(starting);
  const afterCountries = await jobCount(results);

  await choose(page, "Role", "Backend");
  await expect.poll(() => param(page, "role")).toBe("backend");
  await expect.poll(() => jobCount(results)).toBeLessThan(afterCountries);
  const afterRole = await jobCount(results);

  await page.keyboard.press("Escape");
  const slider = page.getByRole("slider", { name: "Minimum fit score" });
  await slider.focus();
  await page.keyboard.press("End");
  await expect.poll(() => param(page, "min_score")).toBe("100");
  await expect.poll(() => jobCount(results)).toBeLessThan(afterRole);

  await page.getByRole("button", { name: "Clear all" }).click();
  await expect.poll(() => page.url()).not.toContain("min_score=");
  await expect.poll(() => jobCount(results)).toBe(starting);
});

async function choose(page: Page, name: string, optionName: string): Promise<void> {
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name, exact: true }).click();
  await page.getByPlaceholder(`Search ${name.toLowerCase()}`).fill(optionName);
  await page.getByRole("option", { name: optionName, exact: true }).click();
}

function param(page: Page, key: string): string {
  return new URL(page.url()).searchParams.get(key) ?? "";
}

async function jobCount(results: Locator): Promise<number> {
  const text = await results.locator("p").first().innerText();
  const match = text.replaceAll(",", "").match(/(\d+)/);
  return Number(match?.[1] ?? "0");
}
