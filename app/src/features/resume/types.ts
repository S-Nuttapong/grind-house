export type ResumeStatus = "queued" | "running" | "ok" | "below_baseline" | "failed";

export type ResumeRun = {
  id: number;
  job_id: number;
  status: ResumeStatus;
  attempts: number;
  baseline_score: number | null;
  baseline_coverage: number | null;
  resume_score: number | null;
  resume_coverage: number | null;
  lost_aspects: string[];
  filler_ids: string[];
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type ResumeStreamEvent = {
  id: number;
  kind: "progress" | "status" | "log";
  stage?: string;
  attempt?: number;
  status?: ResumeStatus;
  error?: string;
};

export type UsageAttempt = {
  id: number;
  run_id: number;
  job_id: number | null;
  attempt: number;
  model: string;
  input_tokens: number;
  output_tokens: number;
  num_turns: number;
  duration_ms: number;
  cost_usd: string;
  created_at: string;
  status: string | null;
};

export type UsageDay = {
  day: string;
  model: string;
  runs: number;
  cost_usd: string;
  input_tokens: number;
  output_tokens: number;
};

export type UsageSummary = {
  days: number;
  runs: number;
  cost_usd: string;
  input_tokens: number;
  output_tokens: number;
  by_day: UsageDay[];
  recent: UsageAttempt[];
};
