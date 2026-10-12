// Mirrors the pydantic models in api/jobhunt/scrape/router.py (see /openapi.json).

export type Run = {
  id: number;
  source_id: string;
  scope_name: string | null;
  status: string;
  fetched: number | null;
  new_jobs: number | null;
  updated: number | null;
  closed: number | null;
  skipped: number;
  error: string | null;
  started_at: string;
  finished_at: string | null;
  source_alert: boolean;
};

export type SearchSource = {
  source_id: string;
  poll_minutes: number;
  enabled: boolean;
  paused_until: string | null;
  strikes: number;
  last_polled_at: string | null;
  last_status: string | null;
};

export type Search = {
  id: number;
  name: string;
  keywords: string[];
  countries: string[];
  timezone: string;
  enabled: boolean;
  sources: SearchSource[];
};

export type ScrapeSettings = { allowed_roles: string[] };

export type TickHook = {
  id: number;
  name: string;
  phase: string;
  exit_code: number | null;
  duration_ms: number;
  ran_at: string;
  error: string | null;
};

export type HooksView = {
  configured: { phase: string; name: string; run: string; timeout?: string; on_fail?: string }[];
  recent: TickHook[];
};
