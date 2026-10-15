"use server";

import { refresh } from "next/cache";

import { postBulkEvents, postBulkResumes, postJobEvent } from "@/features/jobs/api";
import type { JobStatus, MoveStatus } from "@/features/jobs/types";

const STATUSES: ReadonlySet<string> = new Set<MoveStatus>(["saved", "skipped", "applied", "removed"]);
const COLUMN_STATUSES: ReadonlySet<string> = new Set<JobStatus>(["saved", "skipped", "applied"]);

export type EventResult = { ok: true; status: MoveStatus } | { ok: false; error: string };
export type MoveResult = { ok: true; updated: number[] } | { ok: false; error: string };
export type QueueResult =
  | { ok: true; queued: { job_id: number; run_id: number }[]; skipped: { job_id: number; reason: string }[] }
  | { ok: false; error: string };

export async function recordJobEvent(
  jobId: number,
  status: MoveStatus,
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

export async function moveJobs(jobIds: number[], status: MoveStatus): Promise<MoveResult> {
  const ids = cleanIds(jobIds);
  if (ids === null || !STATUSES.has(status)) {
    return { ok: false, error: "Invalid jobs or status" };
  }
  try {
    const result = await postBulkEvents(ids, status);
    refresh();
    return { ok: true, updated: result.updated };
  } catch (error) {
    console.error("moveJobs failed", { count: ids.length, status, error });
    return { ok: false, error: "Could not save. Is the API running?" };
  }
}

export async function restoreJobs(items: { id: number; status: JobStatus }[]): Promise<MoveResult> {
  const groups = new Map<JobStatus, number[]>();
  for (const item of items) {
    if (!Number.isInteger(item.id) || item.id <= 0 || !COLUMN_STATUSES.has(item.status)) {
      return { ok: false, error: "Invalid jobs or status" };
    }
    const bucket = groups.get(item.status) ?? [];
    bucket.push(item.id);
    groups.set(item.status, bucket);
  }
  if (groups.size === 0 || items.length > 300) {
    return { ok: false, error: "Invalid jobs or status" };
  }
  const updated: number[] = [];
  try {
    for (const [status, ids] of groups) {
      const result = await postBulkEvents(ids, status);
      updated.push(...result.updated);
    }
  } catch (error) {
    console.error("restoreJobs failed", { error });
    return { ok: false, error: "Could not save. Is the API running?" };
  }
  refresh();
  return { ok: true, updated };
}

export async function queueResumes(jobIds: number[]): Promise<QueueResult> {
  const ids = cleanIds(jobIds);
  if (ids === null) return { ok: false, error: "Invalid jobs" };
  try {
    const result = await postBulkResumes(ids);
    refresh();
    return { ok: true, queued: result.queued, skipped: result.skipped };
  } catch (error) {
    console.error("queueResumes failed", { count: ids.length, error });
    return { ok: false, error: "Could not queue resumes. Is the API running?" };
  }
}

function cleanIds(jobIds: number[]): number[] | null {
  const ids = [...new Set(jobIds)];
  if (ids.length === 0 || ids.length > 300 || ids.some((id) => !Number.isInteger(id) || id <= 0)) {
    return null;
  }
  return ids;
}
