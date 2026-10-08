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

export type BankMetric = { text: string; confidence?: string };

export type BankRole = "led" | "built" | "co-built" | "contributed";
export type BankStatus = "draft" | "needs-metric" | "verified";

export type BankEntry = {
  id: string;
  title: string;
  company: string | null;
  role: string | null;
  period: string | null;
  my_role: BankRole | null;
  scope: string | null;
  metrics: BankMetric[];
  strength: number | null;
  confidential: boolean;
  status: BankStatus;
  tags: string[];
  body_md: string;
  origin: "vault" | "ui";
  updated_at: string;
};

export type BankEntryInput = {
  id: string;
  title: string;
  company: string | null;
  role: string | null;
  period: string | null;
  my_role: BankRole | null;
  scope: string | null;
  metrics: BankMetric[];
  strength: number | null;
  confidential: boolean;
  status: BankStatus;
  tags: string[];
  body_md: string;
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
