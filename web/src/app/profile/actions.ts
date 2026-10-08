"use server";

import { refresh } from "next/cache";

import { ApiError, removeResume, saveSummary as storeSummary, selectResumeFile, uploadResumeFile } from "@/lib/api";

export type ActionResult = { ok: true } | { ok: false; error: string };

const UPLOAD_SUFFIXES = new Set([".pdf", ".md", ".txt", ".json"]);
const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;

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
