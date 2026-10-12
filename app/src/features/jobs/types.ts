// Mirrors the pydantic models in api/jobhunt/jobs/router.py (see /openapi.json).

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
  coverage: number | null;
  gaps: string[];
  top_brags: { id: string; title: string; aspect: string; similarity: number }[];
};

export type JobPage = {
  jobs: JobSummary[];
  total: number;
  page: number;
  pages: number;
  page_size: number;
};

export type Facets = {
  sources: string[];
  remote: string[];
  countries: string[];
  regions: string[];
  roles: string[];
  industries: string[];
  levels: string[];
};

export type Pipeline = Record<JobStatus, JobSummary[]>;
