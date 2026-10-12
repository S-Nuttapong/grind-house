import type { ResumeRun, ResumeStreamEvent } from "@/features/resume/types";

async function readJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { headers: { accept: "application/json" }, ...init });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `${path} returned ${response.status}`);
  }
  return (await response.json()) as T;
}

export function fetchResumeRuns(jobId: number): Promise<ResumeRun[]> {
  return readJson<ResumeRun[]>(`/api/jobs/${jobId}/resume-runs`);
}

export function fetchResumeRun(runId: number): Promise<ResumeRun> {
  return readJson<ResumeRun>(`/api/resume-runs/${runId}`);
}

export function startResume(jobId: number): Promise<{ run_id: number }> {
  return readJson<{ run_id: number }>(`/api/jobs/${jobId}/resume`, { method: "POST" });
}

export type { ResumeStreamEvent };
