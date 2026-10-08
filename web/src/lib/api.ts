import "server-only";

import type { Facets, JobDetail, JobPage, Pipeline, Run } from "@/lib/types";

const API_URL = process.env.JOBHUNT_API_URL ?? "http://127.0.0.1:8765";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { accept: "application/json", ...init?.headers },
  });
  if (!response.ok) {
    throw new ApiError(response.status, `${init?.method ?? "GET"} ${path} returned ${response.status}`);
  }
  return (await response.json()) as T;
}

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

export function fetchRuns(): Promise<Run[]> {
  return request<Run[]>("/api/runs");
}

export function postJobEvent(id: number, status: string, reason?: string): Promise<JobDetail> {
  return request<JobDetail>(`/api/jobs/${id}/events`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ status, reason: reason ?? null }),
  });
}
