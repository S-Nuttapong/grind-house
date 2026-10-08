// Mirrors the pydantic response models in jobhunt/web/api.py (see /openapi.json).

export type JobStatus = "saved" | "skipped" | "applied";

export type JobSummary = {
  id: number;
  title: string;
  company: string;
  city: string | null;
  country: string | null;
  place: string;
  remote: string | null;
  remote_label: string;
  employment_type: string | null;
  salary_min: string | null;
  salary_max: string | null;
  salary_currency: string | null;
  salary_label: string | null;
  posted_at: string | null;
  first_seen_at: string;
  closed_at: string | null;
  age: string;
  is_new: boolean;
  apply_url: string;
  status: string | null;
  score: number | null;
  band: "apply" | "maybe" | "skip" | null;
  fit_tier: "strong" | "good" | "fair" | "low" | null;
  matched_terms: string[];
  missing_terms: string[];
  stage: string;
  snippet: string;
  sources: string[];
};

export type JobDetail = JobSummary & {
  description_md: string | null;
  postings: { source_id: string; source_url: string | null }[];
  events: { status: string; reason: string | null; note: string | null; origin: string; at: string }[];
  tailor_prompt: string;
};

export type JobPage = {
  jobs: JobSummary[];
  total: number;
  page: number;
  pages: number;
  page_size: number;
};

export type Facets = { sources: string[]; remote: string[] };

export type Pipeline = Record<JobStatus, JobSummary[]>;

export type Tag = {
  id: number;
  name: string;
  color_hex: string;
};

export type MetricKey = {
  id: number;
  name: string;
};

export type BragMetric = {
  id: number;
  metric_key_id: number;
  name: string;
  value: string;
  position: number;
};

export type BragAttachment = {
  id: number;
  type: "url";
  link: string;
  position: number;
};

export type BragDoc = {
  id: string;
  title: string;
  date: string;
  quarter: string;
  company: string | null;
  role: string | null;
  description_md: string;
  origin: "vault" | "ui";
  updated_at: string;
  tags: Tag[];
  metrics: BragMetric[];
  attachments: BragAttachment[];
};

export type BragDocInput = {
  title: string;
  date: string;
  company: string | null;
  role: string | null;
  description_md: string;
  tag_ids: number[];
  metrics: { metric_key_id: number; value: string }[];
  attachments: { type: "url"; link: string }[];
};

export type ResumeFile = {
  id: number;
  name: string;
  filename: string | null;
  text: string;
  origin: "upload" | "vault";
  is_selected: boolean;
  created_at: string;
  text_length: number;
};

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

export type Run = {
  id: number;
  source_id: string;
  scope_name: string | null;
  status: string;
  fetched: number | null;
  new_jobs: number | null;
  updated: number | null;
  closed: number | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
};
