import { ApiError, request } from "@/lib/api-client";
import type { JobDetail, JobPage, Facets, Pipeline } from "@/features/jobs/types";

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

export function fetchPipeline(): Promise<Pipeline> {
  return request<Pipeline>("/api/pipeline");
}

export function postJobEvent(id: number, status: string, reason?: string): Promise<JobDetail> {
  return request<JobDetail>(`/api/jobs/${id}/events`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ status, reason: reason ?? null }),
  });
}
