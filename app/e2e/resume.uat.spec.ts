import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const API = process.env.UAT_API_URL ?? "http://127.0.0.1:8765";
const DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://jobhunt:jobhunt@127.0.0.1:54330/jobhunt?sslmode=disable";

type Job = { id: number; fit_tier: string | null; score: number | null };

test("generate a resume from the job card", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    // Chrome logs this when the resume SSE response closes after the final event.
    if (message.type() === "error" && !message.text().includes("ERR_INCOMPLETE_CHUNKED_ENCODING")) {
      errors.push(message.text());
    }
  });

  const jobs = await chooseJobs();
  test.skip(jobs.length === 0, "no scored jobs with a strong, good, or fair fit");

  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const log: string[] = [`# UAT ${stamp}`, ""];
  const failures: string[] = [];
  for (const job of jobs) {
    const dir = path.join("e2e", "artifacts", stamp, String(job.id));
    fs.mkdirSync(dir, { recursive: true });
    const result = await runJob(page, job, dir);
    log.push(`## job ${job.id} (${job.fit_tier ?? "unrated"})`, "", result.report, "");
    fs.writeFileSync(path.join(dir, "check.txt"), result.report);
    if (!result.statusVisible || result.report.includes("FAIL")) {
      failures.push(`job ${job.id}\n${result.report}`);
    }
  }
  log.push("## console", "", errors.length === 0 ? "PASS  no console errors" : errors.join("\n"));
  const artifacts = path.join("e2e", "artifacts");
  fs.mkdirSync(artifacts, { recursive: true });
  fs.writeFileSync(path.join(artifacts, "uat-log.md"), log.join("\n"));
  expect(errors, errors.join("\n")).toEqual([]);
  expect(failures, failures.join("\n\n")).toEqual([]);
});

async function runJob(page: Page, job: Job, dir: string): Promise<{ report: string; statusVisible: boolean }> {
  await page.goto("/");
  await page.screenshot({ path: path.join(dir, "before.png") });
  const card = page.getByTestId(`job-card-${job.id}`);
  if (await card.count()) {
    await card.click();
  } else {
    await page.goto(`/?jk=${job.id}`);
  }
  await expect(page.getByRole("heading", { name: "Full job description" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Match" })).toBeVisible();
  await page.getByTestId("generate-resume").click();
  const progress = page.getByTestId("resume-progress");
  await expect(progress).toBeVisible();
  await page.screenshot({ path: path.join(dir, "during.png") });
  await expect(page.getByTestId("resume-status")).toBeVisible({ timeout: 300_000 });
  await page.screenshot({ path: path.join(dir, "after.png") });

  const download = page.getByTestId("resume-download");
  const statusVisible = await page.getByTestId("resume-status").isVisible();
  let report = "FAIL  ui: no download link";
  if (await download.count()) {
    const href = await download.getAttribute("href");
    const runId = href?.match(/resume-runs\/(\d+)/)?.[1];
    const response = await page.request.get(href ?? "");
    const pdf = Buffer.from(await response.body());
    fs.writeFileSync(path.join(dir, "resume.pdf"), pdf);
    renderPreview(pdf, dir);
    report = runId ? acceptance(runId) : "FAIL  ui: download link has no run id";
    const filler = page.getByTestId("resume-filler");
    const scores = await page.getByTestId("resume-status").innerText();
    const showedScores = scores.includes("Resume") && scores.includes("shortlist");
    report += `\n${showedScores ? "PASS" : "FAIL"}  ui: scores visible`;
    if (await filler.count()) report += `\nPASS  ui: filler ${await filler.innerText()}`;
  }
  return { report, statusVisible };
}

async function chooseJobs(): Promise<Job[]> {
  if (process.env.UAT_JOB_IDS) {
    return process.env.UAT_JOB_IDS.split(",")
      .map((id) => ({ id: Number(id), fit_tier: null, score: null }))
      .filter((job) => job.id > 0);
  }
  const picked = new Map<string, Job>();
  for (let page = 1; page <= 5 && picked.size < 3; page += 1) {
    const response = await fetch(`${API}/api/jobs?sort=match&min_score=40&page=${page}`);
    if (!response.ok) return [];
    const body = (await response.json()) as { jobs: Job[] };
    for (const job of body.jobs) {
      if (job.fit_tier && ["strong", "good", "fair"].includes(job.fit_tier) && !picked.has(job.fit_tier)) {
        picked.set(job.fit_tier, job);
      }
    }
    if (body.jobs.length === 0) break;
  }
  return [...picked.values()];
}

function acceptance(runId: string): string {
  try {
    return execFileSync("uv", ["run", "jobhunt", "resume", "check", "--run", runId], {
      cwd: path.resolve(process.cwd(), "../api"),
      env: {
        ...process.env,
        DATABASE_URL,
        VAULT_BANK_PATH: process.env.VAULT_BANK_PATH ?? "/tmp/jobhunt-bank",
      },
      encoding: "utf8",
    });
  } catch (error) {
    const failed = error as { stdout?: string; stderr?: string };
    return `${failed.stdout ?? ""}${failed.stderr ?? ""}`.trim() || "FAIL  check command";
  }
}

function renderPreview(pdf: Buffer, dir: string): void {
  const file = path.join(dir, "resume.pdf");
  fs.writeFileSync(file, pdf);
  try {
    execFileSync("pdftoppm", ["-png", "-f", "1", "-l", "1", "-singlefile", file, path.join(dir, "page")], {
      stdio: "ignore",
    });
  } catch {
    fs.writeFileSync(path.join(dir, "page-skipped.txt"), "pdftoppm is not installed");
  }
}
