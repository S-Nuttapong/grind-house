"use server";

import { refresh } from "next/cache";

import { ApiError, removeEntry, removeResume, saveEntry as storeEntry, saveSummary as storeSummary, selectResumeFile, uploadResumeFile } from "@/lib/api";
import type { BankEntryInput, BankRole, BankStatus } from "@/lib/types";

export type ActionResult = { ok: true } | { ok: false; error: string };

const ROLES = new Set<BankRole>(["led", "built", "co-built", "contributed"]);
const STATUSES = new Set<BankStatus>(["draft", "needs-metric", "verified"]);
const UPLOAD_SUFFIXES = new Set([".pdf", ".md", ".txt", ".json"]);
const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;

export async function saveEntry(input: BankEntryInput, mode: "create" | "edit"): Promise<ActionResult> {
  const entry = normalizeEntry(input);
  const error = validateEntry(entry);
  if (error) return { ok: false, error };
  return run(() => storeEntry(entry, mode));
}

export async function deleteEntry(id: string): Promise<ActionResult> {
  if (!id.trim()) return { ok: false, error: "Missing entry" };
  return run(() => removeEntry(id));
}

export async function saveSummary(bodyMd: string): Promise<ActionResult> {
  if (bodyMd.length > 20_000) return { ok: false, error: "Summary is too long" };
  return run(() => storeSummary(bodyMd));
}

export async function uploadResume(formData: FormData): Promise<ActionResult> {
  const file = formData.get("file");
  if (!(file instanceof File) || file.size === 0) {
    return { ok: false, error: "Choose a .pdf, .md, .txt, or .json file" };
  }
  const suffix = file.name.includes(".") ? `.${file.name.split(".").pop()?.toLowerCase()}` : "";
  if (!UPLOAD_SUFFIXES.has(suffix)) return { ok: false, error: "Upload a .pdf, .md, .txt, or .json file" };
  if (file.size > MAX_UPLOAD_BYTES) return { ok: false, error: "File is over 5 MB" };
  return run(() => uploadResumeFile(file));
}

export async function selectResume(id: number): Promise<ActionResult> {
  if (!Number.isInteger(id) || id <= 0) return { ok: false, error: "Missing resume" };
  return run(() => selectResumeFile(id));
}

export async function deleteResume(id: number): Promise<ActionResult> {
  if (!Number.isInteger(id) || id <= 0) return { ok: false, error: "Missing resume" };
  return run(() => removeResume(id));
}

function normalizeEntry(input: BankEntryInput): BankEntryInput {
  return {
    ...input,
    id: input.id.trim(),
    title: input.title.trim(),
    company: input.company?.trim() || null,
    role: input.role?.trim() || null,
    period: input.period?.trim() || null,
    scope: input.scope?.trim() || null,
    tags: [...new Set(input.tags.map((tag) => tag.trim()).filter(Boolean))],
    metrics: input.metrics
      .map((metric) => ({
        text: metric.text.trim(),
        ...(metric.confidence?.trim() ? { confidence: metric.confidence.trim() } : {}),
      }))
      .filter((metric) => metric.text),
    body_md: input.body_md,
  };
}

function validateEntry(input: BankEntryInput): string | null {
  const id = input.id.trim();
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,40}$/.test(id)) {
    return "Id should look like BB-001";
  }
  if (!input.title.trim() || input.title.trim().length > 200) return "Title is required";
  if (input.my_role !== null && !ROLES.has(input.my_role)) return "Choose a valid role";
  if (!STATUSES.has(input.status)) return "Choose a valid status";
  if (input.strength !== null && (!Number.isInteger(input.strength) || input.strength < 1 || input.strength > 5)) {
    return "Strength is 1 to 5";
  }
  if (input.tags.length > 40 || input.tags.some((tag) => !tag.trim() || tag.length > 60)) {
    return "Check the tags";
  }
  if (input.metrics.length > 30 || input.metrics.some((metric) => !metric.text.trim() || metric.text.length > 300)) {
    return "Each metric needs a short result";
  }
  if (input.body_md.length > 20_000) return "The write-up is too long";
  return null;
}

async function run(work: () => Promise<unknown>): Promise<ActionResult> {
  try {
    await work();
  } catch (error) {
    console.error("profile action failed", error);
    return { ok: false, error: error instanceof ApiError ? error.message : "Could not save. Is the API running?" };
  }
  refresh();
  return { ok: true };
}
