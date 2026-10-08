import "server-only";

import type { BankEntry, BankEntryInput, Facets, JobDetail, JobPage, Pipeline, ResumeFile, Run } from "@/lib/types";

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
    throw new ApiError(response.status, await errorMessage(response, init?.method ?? "GET", path));
  }
  if (response.status === 204) return undefined as T;
  const body = await response.text();
  return (body ? JSON.parse(body) : undefined) as T;
}

async function errorMessage(response: Response, method: string, path: string): Promise<string> {
  const fallback = `${method} ${path} returned ${response.status}`;
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string" && payload.detail) return payload.detail;
  } catch {
    return fallback;
  }
  return fallback;
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

export function fetchEntries(): Promise<BankEntry[]> {
  return request<BankEntry[]>("/api/profile/entries");
}

export function fetchSummary(): Promise<{ body_md: string }> {
  return request<{ body_md: string }>("/api/profile/summary");
}

export function saveEntry(entry: BankEntryInput, mode: "create" | "edit"): Promise<BankEntry> {
  const path = mode === "create" ? "/api/profile/entries" : `/api/profile/entries/${encodeURIComponent(entry.id)}`;
  return request<BankEntry>(path, {
    method: mode === "create" ? "POST" : "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(entry),
  });
}

export function removeEntry(id: string): Promise<void> {
  return request<void>(`/api/profile/entries/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function saveSummary(bodyMd: string): Promise<{ body_md: string }> {
  return request<{ body_md: string }>("/api/profile/summary", {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ body_md: bodyMd }),
  });
}

export function fetchResumes(): Promise<ResumeFile[]> {
  return request<ResumeFile[]>("/api/resumes");
}

export function uploadResumeFile(file: File): Promise<ResumeFile> {
  const body = new FormData();
  body.append("file", file, file.name);
  return request<ResumeFile>("/api/resumes", { method: "POST", body });
}

export function selectResumeFile(id: number): Promise<ResumeFile> {
  return request<ResumeFile>(`/api/resumes/${id}/select`, { method: "POST" });
}

export function removeResume(id: number): Promise<void> {
  return request<void>(`/api/resumes/${id}`, { method: "DELETE" });
}

export function postJobEvent(id: number, status: string, reason?: string): Promise<JobDetail> {
  return request<JobDetail>(`/api/jobs/${id}/events`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ status, reason: reason ?? null }),
  });
}
