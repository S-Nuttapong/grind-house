// Mirrors the pydantic models in api/jobhunt/fit/router.py (see /openapi.json).

export type FitMode = "bank" | "resume";

export type ScheduleInput = {
  name: string;
  mode: FitMode;
  cron: string;
  timezone: string;
  enabled: boolean;
};

export type FitSchedule = ScheduleInput & {
  id: number;
  last_run_at: string | null;
  next_run_at: string | null;
  description: string;
  upcoming: string[];
  last_run: FitRun | null;
};

export type FitRunStatus = "queued" | "running" | "ok" | "failed";

export type FitRun = {
  id: number;
  schedule_id: number | null;
  mode: FitMode;
  trigger: "schedule" | "manual" | "scrape";
  model_id: string;
  status: FitRunStatus;
  scored: number;
  skipped: number;
  error: string | null;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type FitProgress = {
  id: number;
  kind: string;
  payload: { done?: number; total?: number; pct?: number; status?: string };
  at: string;
};

export type FitRunDetail = FitRun & { progress: FitProgress | null };

export type FitStreamEvent = {
  id: number;
  kind: string;
  done?: number;
  total?: number;
  pct?: number;
  status?: string;
};

export type FitStatus = {
  worker: { model_id: string | null; heartbeat_at: string | null };
  modes: Record<FitMode, { source_hash: string | null; stale: boolean }>;
};
