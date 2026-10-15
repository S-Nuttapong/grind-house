import { ApiError, request } from "@/lib/apiClient";
import type { JobDetail, JobPage, Facets, Tracker } from "@/features/jobs/types";

export function fetchJobs(query: string): Promise<JobPage> {
  return request<JobPage>(`/api/jobs${query ? `?${query}` : ""}`);
}

export async function fetchJob(id: number, fit = ""): Promise<JobDetail | null> {
  try {
    return await request<JobDetail>(`/api/jobs/${id}${fit === "resume" ? "?fit=resume" : ""}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export function fetchFacets(): Promise<Facets> {
  return request<Facets>("/api/facets");
}

export function fetchTracker(): Promise<Tracker> {
  return request<Tracker>("/api/tracker");
}

export function postTrackerOrder(columns: {
  saved: number[];
  applied: number[];
  skipped: number[];
}): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>("/api/tracker/order", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(columns),
  });
}

export function postBulkEvents(
  ids: number[],
  status: string,
  reason?: string,
): Promise<{ updated: number[] }> {
  return request<{ updated: number[] }>("/api/jobs/events/bulk", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ job_ids: ids, status, reason: reason ?? null }),
  });
}

export function postBulkResumes(
  ids: number[],
): Promise<{ queued: { job_id: number; run_id: number }[]; skipped: { job_id: number; reason: string }[] }> {
  return request("/api/resume-runs/bulk", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ job_ids: ids }),
  });
}

export function postJobEvent(id: number, status: string, reason?: string): Promise<JobDetail> {
  return request<JobDetail>(`/api/jobs/${id}/events`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ status, reason: reason ?? null }),
  });
}
