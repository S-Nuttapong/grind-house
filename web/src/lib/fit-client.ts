import type { FitRun, FitRunDetail, FitSchedule, FitStatus } from "@/lib/types";

async function readJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { accept: "application/json" } });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return (await response.json()) as T;
}

export function fetchFitSchedules(): Promise<FitSchedule[]> {
  return readJson<FitSchedule[]>("/api/fit/schedules");
}

export function fetchFitRuns(): Promise<FitRun[]> {
  return readJson<FitRun[]>("/api/fit/runs");
}

export function fetchFitRun(id: number): Promise<FitRunDetail> {
  return readJson<FitRunDetail>(`/api/fit/runs/${id}`);
}

export function fetchFitStatus(): Promise<FitStatus> {
  return readJson<FitStatus>("/api/fit/status");
}
