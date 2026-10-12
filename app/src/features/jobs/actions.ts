"use server";

import { refresh } from "next/cache";

import { postJobEvent } from "@/features/jobs/api";
import type { JobStatus } from "@/features/jobs/types";

const STATUSES: ReadonlySet<string> = new Set<JobStatus>(["saved", "skipped", "applied"]);

export type EventResult = { ok: true; status: JobStatus } | { ok: false; error: string };

export async function recordJobEvent(
  jobId: number,
  status: JobStatus,
  reason?: string,
): Promise<EventResult> {
  if (!Number.isInteger(jobId) || jobId <= 0 || !STATUSES.has(status)) {
    return { ok: false, error: "Invalid job or status" };
  }
  try {
    await postJobEvent(jobId, status, reason?.trim().slice(0, 500) || undefined);
  } catch (error) {
    console.error("recordJobEvent failed", { jobId, status, error });
    return { ok: false, error: "Could not save. Is the API running?" };
  }
  refresh();
  return { ok: true, status };
}
