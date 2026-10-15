-- Job Hunt OS schema · Postgres 16+ · v0.5
-- Relational core, JSONB only where the shape varies (source params, raw payloads, LLM output, filters).

CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- fuzzy title match for dedupe and search
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- sha256 so the fit worker can find changed jobs

-- ───────────── Reference ─────────────

CREATE TABLE sources (
  id            text PRIMARY KEY,                       -- 'greenhouse', 'linkedin_guest', 'adzuna'
  kind          text NOT NULL CHECK (kind IN ('ats','aggregator','feed')),
  min_interval  interval NOT NULL,                      -- schedule guardrail
  close_after   interval,                               -- aggregators: close if unseen this long
  enabled       boolean NOT NULL DEFAULT true
);

CREATE TABLE companies (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name         text NOT NULL,
  name_norm    text NOT NULL UNIQUE,                    -- lowercased, suffixes (Inc, Pte Ltd) stripped
  tier         char(1) CHECK (tier IN ('A','B','C')),   -- null = discovered, not yet reviewed
  ats          text REFERENCES sources(id),
  ats_slug     text,
  careers_url  text,
  excluded     boolean NOT NULL DEFAULT false,
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (ats, ats_slug)
);

CREATE TABLE company_aliases (                          -- "Grab Holdings", "GrabTaxi" → Grab
  alias_norm  text PRIMARY KEY,
  company_id  bigint NOT NULL REFERENCES companies(id) ON DELETE CASCADE
);

-- ───────────── Fetching ─────────────

CREATE TABLE fetch_scopes (                             -- what to collect, and when (UI-editable)
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name         text NOT NULL,
  source_id    text NOT NULL REFERENCES sources(id),
  params       jsonb NOT NULL,                          -- ATS: {"tiers":["A","B"]}; JobSpy: {"search_term":..., "location":..., "hours_old":48}
  cron         text NOT NULL,
  timezone     text NOT NULL DEFAULT 'Asia/Bangkok',
  enabled      boolean NOT NULL DEFAULT true,
  last_run_at  timestamptz,
  next_run_at  timestamptz,
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE runs (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scope_id         bigint REFERENCES fetch_scopes(id) ON DELETE SET NULL,
  source_id        text NOT NULL REFERENCES sources(id),
  started_at       timestamptz NOT NULL DEFAULT now(),
  finished_at      timestamptz,
  search_id        bigint,                                 -- set when a search poll started the run
  status           text NOT NULL DEFAULT 'running' CHECK (status IN ('running','ok','partial','failed','skipped')),
  fetched          int NOT NULL DEFAULT 0,
  new_jobs         int NOT NULL DEFAULT 0,
  updated          int NOT NULL DEFAULT 0,
  closed           int NOT NULL DEFAULT 0,
  skipped          int NOT NULL DEFAULT 0,                 -- off-topic titles dropped
  error            text,
  scraper_version  text NOT NULL
);
CREATE INDEX runs_source_started ON runs (source_id, started_at DESC);

CREATE TABLE searches (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name        text NOT NULL,
  keywords    text[] NOT NULL,
  countries   char(2)[] NOT NULL,
  timezone    text NOT NULL DEFAULT 'Asia/Bangkok',
  enabled     boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE search_sources (
  search_id        bigint NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
  source_id        text NOT NULL REFERENCES sources(id),
  poll_minutes     int NOT NULL DEFAULT 30,
  paused_until     timestamptz,
  strikes          int NOT NULL DEFAULT 0,
  enabled          boolean NOT NULL DEFAULT true,
  last_catchup_at  timestamptz,
  cursor           jsonb,
  PRIMARY KEY (search_id, source_id)
);

ALTER TABLE runs
  ADD CONSTRAINT runs_search_id_fkey
  FOREIGN KEY (search_id) REFERENCES searches(id) ON DELETE SET NULL;

CREATE TABLE search_markets (
  search_id       bigint NOT NULL,
  source_id       text NOT NULL,
  country         char(2) NOT NULL,
  last_polled_at  timestamptz,
  last_status     text,
  PRIMARY KEY (search_id, source_id, country),
  FOREIGN KEY (search_id, source_id)
    REFERENCES search_sources (search_id, source_id) ON DELETE CASCADE
);

CREATE TABLE scrape_settings (
  id             boolean PRIMARY KEY DEFAULT true CHECK (id),
  allowed_roles  text[] NOT NULL
);

CREATE TABLE tick_hooks (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name         text NOT NULL,
  phase        text NOT NULL,
  exit_code    int,
  duration_ms  int NOT NULL,
  ran_at       timestamptz NOT NULL DEFAULT now(),
  error        text
);

-- ───────────── Jobs ─────────────

CREATE DOMAIN currency_code AS text CHECK (VALUE ~ '^[A-Z]{3}$');  -- ISO 4217
CREATE DOMAIN money_amount AS numeric CHECK (VALUE > 0);           -- exact; never the money type
CREATE DOMAIN months AS smallint CHECK (VALUE BETWEEN 0 AND 600);  -- 0 = none required

CREATE TABLE jobs (                                     -- one row per real job (canonical)
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  company_id       bigint NOT NULL REFERENCES companies(id),
  title            text NOT NULL,
  title_norm       text NOT NULL,
  level            text NOT NULL DEFAULT 'unknown'
                   CHECK (level IN ('intern','junior','mid','senior','staff','principal','lead','manager','unknown')),
  role             text,                                -- taxonomy slug; null when the title does not match
  industry         text,                                -- taxonomy slug; null when unknown
  country          char(2),                             -- ISO 3166-1 alpha-2
  city             text,
  remote           text NOT NULL DEFAULT 'unknown' CHECK (remote IN ('onsite','hybrid','remote','unknown')),
  tz_min           smallint CHECK (tz_min BETWEEN -12 AND 14),   -- allowed UTC offsets for remote roles
  tz_max           smallint CHECK (tz_max BETWEEN -12 AND 14),
  employment_type  text CHECK (employment_type IN ('fulltime','parttime','contract','internship','temporary')),
  salary_min       numeric(12,0),
  salary_max       numeric(12,0),
  salary_currency  char(3),
  salary_interval  text CHECK (salary_interval IN ('yearly','monthly','weekly','daily','hourly')),
  salary_usd_year_min numeric(12,0),                    -- normalized by the app for filtering
  experience_min_years smallint CHECK (experience_min_years BETWEEN 0 AND 20),
  experience_max_years smallint CHECK (experience_max_years BETWEEN 0 AND 20),
  experience_min_months months,                         -- 0 = none required, NULL = not stated
  experience_max_months months,                         -- NULL = no stated upper bound
  posted_at        date,
  first_seen_at    timestamptz NOT NULL DEFAULT now(),
  last_seen_at     timestamptz NOT NULL DEFAULT now(),
  closed_at        timestamptz,
  apply_url        text NOT NULL,                       -- prefers the company ATS over aggregator links
  description_md   text,                                -- dropped by retention for old, untouched jobs
  locations        jsonb NOT NULL DEFAULT '[]',         -- every place, not just the primary city
  countries        char(2)[] NOT NULL DEFAULT '{}',
  fact_origins     jsonb NOT NULL DEFAULT '{}',         -- field -> parser_id that filled it
  dedupe_key       text NOT NULL,                       -- company_id|title_norm|country
  search           tsvector GENERATED ALWAYS AS (
                     setweight(to_tsvector('english', coalesce(title,'')), 'A') ||
                     setweight(to_tsvector('english', coalesce(description_md,'')), 'B')
                   ) STORED,
  CHECK (salary_max IS NULL OR salary_min IS NULL OR salary_max >= salary_min),
  CONSTRAINT jobs_experience_order CHECK (
    experience_max_years IS NULL
    OR experience_min_years IS NULL
    OR experience_max_years >= experience_min_years
  ),
  CONSTRAINT jobs_experience_months_order CHECK (experience_max_months >= experience_min_months),
  CONSTRAINT jobs_experience_months_has_min CHECK (
    experience_max_months IS NULL OR experience_min_months IS NOT NULL
  )
);
CREATE INDEX jobs_open       ON jobs (posted_at DESC) WHERE closed_at IS NULL;
CREATE INDEX jobs_place      ON jobs (country, remote) WHERE closed_at IS NULL;
CREATE INDEX jobs_dedupe     ON jobs (dedupe_key);
CREATE INDEX jobs_company    ON jobs (company_id);
CREATE INDEX jobs_search     ON jobs USING gin (search);
CREATE INDEX jobs_title_trgm ON jobs USING gin (title_norm gin_trgm_ops);
CREATE INDEX jobs_role       ON jobs (role) WHERE closed_at IS NULL AND role IS NOT NULL;
CREATE INDEX jobs_experience_min ON jobs (experience_min_years)
  WHERE closed_at IS NULL AND experience_min_years IS NOT NULL;
CREATE INDEX jobs_experience_months_min ON jobs (experience_min_months)
  WHERE closed_at IS NULL;

-- Pay components. At most one base row per job. Annual amounts are generated.
-- USD is not stored: job_base_pay joins fx_rates at read time.
CREATE TABLE fx_rates (
  currency     currency_code PRIMARY KEY,
  usd_per_unit numeric NOT NULL CHECK (usd_per_unit > 0),  -- USD for 1 unit of currency
  as_of        date NOT NULL,                              -- provider rate date
  source       text NOT NULL CHECK (source IN ('frankfurter', 'open_er_api')),
  fetched_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE job_compensation (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  job_id         bigint NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  type           text NOT NULL CHECK (type IN (
                   'base', 'bonus', 'signing_bonus', 'equity',
                   'profit_sharing', 'commission', 'tips', 'other')),
  unit           text CHECK (unit IN ('hourly', 'daily', 'weekly', 'monthly', 'yearly', 'one_time')),
  currency       currency_code NOT NULL,
  min_amount     money_amount,                          -- inclusive; NULL = open
  max_amount     money_amount,
  units_per_year numeric CHECK (units_per_year > 0),    -- hourly 2080, daily 260, weekly 52, monthly 12, yearly 1
  annual_min     numeric GENERATED ALWAYS AS (COALESCE(min_amount, max_amount) * units_per_year) STORED,
  annual_max     numeric GENERATED ALWAYS AS (COALESCE(max_amount, min_amount) * units_per_year) STORED,
  evidence       text CHECK (evidence <> ''),           -- NULL only when parser_id is api:%
  parser_id      text NOT NULL,
  updated_at     timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT job_compensation_has_amount CHECK (min_amount IS NOT NULL OR max_amount IS NOT NULL),
  CONSTRAINT job_compensation_order CHECK (max_amount >= min_amount),
  CONSTRAINT job_compensation_unit_year CHECK ((unit IS NULL) = (units_per_year IS NULL)),
  CONSTRAINT job_compensation_base_unit CHECK (type <> 'base' OR unit <> 'one_time'),
  CONSTRAINT job_compensation_evidence CHECK (evidence IS NOT NULL OR parser_id LIKE 'api:%')
);
CREATE UNIQUE INDEX job_compensation_one_base ON job_compensation (job_id) WHERE type = 'base';

CREATE VIEW job_base_pay AS
SELECT c.job_id, c.currency, c.unit, c.min_amount, c.max_amount, c.units_per_year,
       c.annual_min, c.annual_max,
       round(c.annual_min * fx.usd_per_unit) AS usd_annual_min,
       round(c.annual_max * fx.usd_per_unit) AS usd_annual_max,
       fx.as_of AS fx_as_of,
       c.evidence, c.parser_id
FROM job_compensation c
LEFT JOIN fx_rates fx ON fx.currency = c.currency
WHERE c.type = 'base';
CREATE INDEX jobs_industry   ON jobs (industry) WHERE closed_at IS NULL AND industry IS NOT NULL;
CREATE INDEX jobs_countries  ON jobs USING gin (countries);

CREATE TABLE postings (                                 -- each place a job was seen
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  job_id         bigint NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  source_id      text NOT NULL REFERENCES sources(id),
  source_job_id  text NOT NULL,
  source_url     text NOT NULL,
  content_hash   text NOT NULL,                         -- detects JD edits
  first_seen_at  timestamptz NOT NULL DEFAULT now(),
  last_seen_at   timestamptz NOT NULL DEFAULT now(),
  first_run_id   bigint REFERENCES runs(id) ON DELETE SET NULL,
  last_run_id    bigint REFERENCES runs(id) ON DELETE SET NULL,
  detail_status  text NOT NULL DEFAULT 'done' CHECK (detail_status IN ('pending','done','failed','gone')),
  detail_attempts int NOT NULL DEFAULT 0,
  facts          jsonb,                                 -- JobDetail from api + parsers
  facts_status   text NOT NULL DEFAULT 'done' CHECK (facts_status IN ('pending','done','failed')),
  UNIQUE (source_id, source_job_id)
);
CREATE INDEX postings_job ON postings (job_id);
CREATE INDEX postings_detail_pending ON postings (first_seen_at) WHERE detail_status = 'pending';
CREATE INDEX postings_facts_pending ON postings (id) WHERE facts_status = 'pending';

CREATE TABLE raw_payloads (                             -- kept only when content_hash changes; 14-day retention
  posting_id  bigint NOT NULL REFERENCES postings(id) ON DELETE CASCADE,
  run_id      bigint NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  payload     jsonb NOT NULL,
  fetched_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (posting_id, run_id)
);
CREATE INDEX raw_payloads_fetched ON raw_payloads (fetched_at);

-- ───────────── Matching ─────────────

CREATE TABLE profiles (                                 -- versions of profile.json from the brag bank
  hash        text PRIMARY KEY,                         -- sha256 of the file
  profile     jsonb NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE requirements (                             -- LLM extraction of the JD
  job_id          bigint NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  prompt_version  text NOT NULL,
  model           text NOT NULL,
  extracted       jsonb NOT NULL,                       -- {level, must[], nice[], stack[], domain[], logistics{}}
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (job_id, prompt_version)
);

CREATE TABLE prefilter (                                -- deterministic stage: hard filters + keyword score
  job_id         bigint PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
  profile_hash   text NOT NULL REFERENCES profiles(hash),
  passed_hard    boolean NOT NULL,
  filter_reason  text,                                  -- first failing hard filter, e.g. 'level:junior'
  score          real,                                  -- null when passed_hard is false
  shortlisted    boolean NOT NULL DEFAULT false,        -- picked for LLM assessment
  computed_at    timestamptz NOT NULL DEFAULT now(),
  CHECK (passed_hard OR (score IS NULL AND NOT shortlisted)),
  CHECK (passed_hard OR filter_reason IS NOT NULL)
);
CREATE INDEX prefilter_shortlist ON prefilter (score DESC) WHERE shortlisted;

CREATE TABLE matches (                                  -- LLM-assessed, code-scored
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  job_id           bigint NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  profile_hash     text NOT NULL REFERENCES profiles(hash),
  prompt_version   text NOT NULL,
  model            text NOT NULL,
  score            smallint NOT NULL CHECK (score BETWEEN 0 AND 100),
  band             text NOT NULL CHECK (band IN ('apply','maybe','skip')),
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (job_id, profile_hash, prompt_version)
);
CREATE INDEX matches_band ON matches (band, score DESC);

CREATE TABLE match_criteria (                           -- one row per rubric line, so gaps are queryable
  match_id     bigint NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
  ordinal      smallint NOT NULL,
  criterion    text NOT NULL CHECK (criterion IN ('must_have','level','stack','domain','logistics')),
  requirement  text NOT NULL,
  jd_quote     text,
  label        text NOT NULL CHECK (label IN ('met','adjacent','gap','unknown')),
  evidence     text[] NOT NULL DEFAULT '{}',            -- brag bank ids, e.g. {BB-012}
  evidence_ok  boolean NOT NULL DEFAULT false,          -- set by code after checking the bank
  note         text,
  PRIMARY KEY (match_id, ordinal),
  CHECK (label NOT IN ('met','adjacent') OR cardinality(evidence) > 0)
);
CREATE INDEX match_criteria_gaps ON match_criteria (criterion, requirement) WHERE label = 'gap';

-- ───────────── You ─────────────

CREATE TABLE rules (                                    -- saved board filters + notification
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name              text NOT NULL,
  filters           jsonb NOT NULL,                     -- same filter model as the board
  notify_min_score  smallint CHECK (notify_min_score BETWEEN 0 AND 100),
  enabled           boolean NOT NULL DEFAULT true,
  created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE rule_hits (
  rule_id      bigint NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
  job_id       bigint NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  matched_at   timestamptz NOT NULL DEFAULT now(),
  notified_at  timestamptz,
  PRIMARY KEY (rule_id, job_id)
);

CREATE TABLE job_events (                               -- append-only status history
  id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  job_id   bigint NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  status   text NOT NULL CHECK (status IN ('saved','skipped','applied','screening','interviewing','offer','rejected','withdrawn','removed')),
  reason   text,                                        -- skip reason feeds calibration
  note     text,
  origin   text NOT NULL DEFAULT 'ui' CHECK (origin IN ('ui','claude','gmail')),
  at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX job_events_job ON job_events (job_id, at DESC);

CREATE VIEW job_status AS
  SELECT job_id, status, at FROM (
    SELECT DISTINCT ON (job_id) job_id, status, at
    FROM job_events ORDER BY job_id, at DESC
  ) latest
  WHERE status <> 'removed';

CREATE TABLE pipeline_ranks (                       -- manual order inside a column
  job_id  bigint PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
  rank    integer NOT NULL
);

CREATE TABLE labels (                                   -- calibration ground truth
  job_id      bigint PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
  label       text NOT NULL CHECK (label IN ('apply','maybe','skip')),
  origin      text NOT NULL CHECK (origin IN ('calibration','ui_action')),
  labeled_at  timestamptz NOT NULL DEFAULT now()
);

-- ───────────── Job fit (§13.8) ─────────────

-- ───────────── Profile (brag docs + resumes) ─────────────

CREATE TABLE tags (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name       text NOT NULL,
  color_hex  text NOT NULL CHECK (color_hex ~ '^#[0-9A-Fa-f]{6}$')
);
CREATE UNIQUE INDEX tags_name_lower ON tags (lower(name));

CREATE TABLE metric_keys (
  id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name  text NOT NULL
);
CREATE UNIQUE INDEX metric_keys_name_lower ON metric_keys (lower(name));

CREATE TABLE brag_docs (
  id              text PRIMARY KEY,                    -- 'BB-001'
  title           text NOT NULL,
  date            date NOT NULL,
  quarter         text GENERATED ALWAYS AS (
                    'Q' || extract(quarter FROM date)::int::text
                    || ' ' || extract(year FROM date)::int::text
                  ) STORED,
  company         text,
  role            text,
  description_md  text NOT NULL DEFAULT '',
  origin          text NOT NULL DEFAULT 'ui' CHECK (origin IN ('vault','ui')),
  impact          smallint CHECK (impact BETWEEN 1 AND 5),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE brag_doc_tags (
  brag_doc_id  text NOT NULL REFERENCES brag_docs(id) ON DELETE CASCADE,
  tag_id       bigint NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  PRIMARY KEY (brag_doc_id, tag_id)
);

CREATE TABLE brag_doc_metrics (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  brag_doc_id     text NOT NULL REFERENCES brag_docs(id) ON DELETE CASCADE,
  metric_key_id   bigint NOT NULL REFERENCES metric_keys(id) ON DELETE RESTRICT,
  value           text NOT NULL,
  position        integer NOT NULL
);

CREATE TABLE brag_doc_attachments (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  brag_doc_id  text NOT NULL REFERENCES brag_docs(id) ON DELETE CASCADE,
  type         text NOT NULL CHECK (type IN ('url')),
  link         text NOT NULL CHECK (link ~ '^https?://'),
  position     integer NOT NULL
);

CREATE TABLE bank_profile (                           -- single row; no contact details
  id        boolean PRIMARY KEY DEFAULT true CHECK (id),
  body_md   text NOT NULL DEFAULT '',
  updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO bank_profile (body_md) VALUES ('');

CREATE TABLE resumes (                                 -- extracted text only, never the file
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name         text NOT NULL,
  filename     text,
  text         text NOT NULL,
  origin       text NOT NULL DEFAULT 'upload' CHECK (origin IN ('upload','vault')),
  is_selected  boolean NOT NULL DEFAULT false,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX resumes_one_selected ON resumes (is_selected) WHERE is_selected;

-- ───────────── Fit scoring ─────────────

CREATE TABLE fit_sources (                             -- one row per version of a profile text
  hash        text PRIMARY KEY,                        -- sha256 of the text that was scored
  kind        text NOT NULL CHECK (kind IN ('bank','resume')),
  resume_id   bigint REFERENCES resumes(id) ON DELETE SET NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  scored_at   timestamptz                              -- set when a run over this source finishes
);

CREATE TABLE job_fits (
  job_id         bigint NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  model_id       text NOT NULL,
  source_hash    text NOT NULL REFERENCES fit_sources(hash),
  job_hash       text NOT NULL,                        -- sha256 of title + description at scoring time
  score          real NOT NULL CHECK (score BETWEEN 0 AND 100),
  raw            real NOT NULL,
  coverage       real,
  gaps           text[] NOT NULL DEFAULT '{}',
  matched_terms  text[] NOT NULL DEFAULT '{}',
  missing_terms  text[] NOT NULL DEFAULT '{}',
  computed_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (job_id, model_id, source_hash)
);
CREATE INDEX job_fits_rank ON job_fits (source_hash, model_id, score DESC);

CREATE TABLE job_fit_matches (
  job_id       bigint NOT NULL,
  model_id     text NOT NULL,
  source_hash  text NOT NULL,
  rank         integer NOT NULL CHECK (rank > 0),
  doc_ref      text NOT NULL,
  aspect       text NOT NULL,
  similarity   real NOT NULL CHECK (similarity BETWEEN 0 AND 1),
  PRIMARY KEY (job_id, model_id, source_hash, rank),
  FOREIGN KEY (job_id, model_id, source_hash)
    REFERENCES job_fits (job_id, model_id, source_hash) ON DELETE CASCADE
);

CREATE TABLE fit_schedules (                           -- the only place cron is stored
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name         text NOT NULL,
  mode         text NOT NULL CHECK (mode IN ('bank','resume')),
  cron         text NOT NULL,
  timezone     text NOT NULL DEFAULT 'Asia/Bangkok',
  enabled      boolean NOT NULL DEFAULT true,
  last_run_at  timestamptz,
  next_run_at  timestamptz,
  updated_at   timestamptz NOT NULL DEFAULT now()
);

INSERT INTO fit_schedules (name, mode, cron, enabled) VALUES
  ('Brag bank daily 06:00', 'bank', '0 6 * * *', true),
  ('Selected resume daily 06:30', 'resume', '30 6 * * *', false);

CREATE TABLE fit_runs (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  schedule_id      bigint REFERENCES fit_schedules(id) ON DELETE SET NULL,
  mode             text NOT NULL CHECK (mode IN ('bank','resume')),
  trigger          text NOT NULL CHECK (trigger IN ('schedule','manual','scrape')),
  model_id         text NOT NULL,
  status           text NOT NULL DEFAULT 'queued'
                   CHECK (status IN ('queued','running','ok','failed')),
  scored           int NOT NULL DEFAULT 0,
  skipped          int NOT NULL DEFAULT 0,
  error            text,
  idempotency_key  text NOT NULL,
  queued_at        timestamptz NOT NULL DEFAULT now(),
  started_at       timestamptz,
  finished_at      timestamptz
);
CREATE UNIQUE INDEX fit_runs_idempotency ON fit_runs (idempotency_key);
CREATE INDEX fit_runs_queue ON fit_runs (queued_at) WHERE status = 'queued';

CREATE TABLE fit_run_events (                          -- append-only; replayed by the SSE stream
  id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id   bigint NOT NULL REFERENCES fit_runs(id) ON DELETE CASCADE,
  kind     text NOT NULL CHECK (kind IN ('status','progress','log')),
  payload  jsonb NOT NULL,
  at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX fit_run_events_run ON fit_run_events (run_id, id);

CREATE TABLE fit_worker (                              -- single row, the worker's heartbeat
  id           boolean PRIMARY KEY DEFAULT true CHECK (id),
  model_id     text,
  heartbeat_at timestamptz
);
INSERT INTO fit_worker (model_id) VALUES (NULL);

-- ───────────── Resume generation (ADR-0005) ─────────────

CREATE TABLE resume_runs (
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  job_id              bigint NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  agent_id            text NOT NULL,
  model               text NOT NULL,
  fit_model_id        text NOT NULL,
  fit_source_hash     text NOT NULL,
  status              text NOT NULL DEFAULT 'queued'
                      CHECK (status IN ('queued','running','ok','below_baseline','failed')),
  locked_until        timestamptz,
  attempts            integer NOT NULL DEFAULT 0
  baseline_score      real,
  baseline_coverage   real,
  resume_score        real,
  resume_coverage     real,
  lost_aspects        text[] NOT NULL DEFAULT '{}',
  filler_ids          text[] NOT NULL DEFAULT '{}',
  error               text,
  created_at          timestamptz NOT NULL DEFAULT now(),
  started_at          timestamptz,
  finished_at         timestamptz
);
CREATE UNIQUE INDEX resume_runs_one_active
  ON resume_runs (job_id) WHERE status IN ('queued', 'running');
CREATE INDEX resume_runs_queue ON resume_runs (created_at)
  WHERE status IN ('queued', 'running');

CREATE TABLE resume_run_events (
  id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id   bigint NOT NULL REFERENCES resume_runs(id) ON DELETE CASCADE,
  kind     text NOT NULL CHECK (kind IN ('status','progress','log')),
  payload  jsonb NOT NULL,
  at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX resume_run_events_run ON resume_run_events (run_id, id);

CREATE TABLE resume_artifacts (
  run_id       bigint PRIMARY KEY REFERENCES resume_runs(id) ON DELETE CASCADE,
  pdf          bytea NOT NULL,
  resume_json  jsonb NOT NULL,
  lint_report  text NOT NULL DEFAULT ''
);

CREATE TABLE agent_usage (
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_kind            text NOT NULL,
  run_id              bigint NOT NULL,
  attempt             integer NOT NULL,
  agent_id            text NOT NULL,
  model               text NOT NULL,
  input_tokens        integer NOT NULL DEFAULT 0,
  output_tokens       integer NOT NULL DEFAULT 0,
  cache_read_tokens   integer NOT NULL DEFAULT 0,
  cache_write_tokens  integer NOT NULL DEFAULT 0,
  num_turns           integer NOT NULL DEFAULT 0,
  duration_ms         integer NOT NULL DEFAULT 0,
  cost_usd            numeric(12, 6) NOT NULL,
  cost_source         text NOT NULL CHECK (cost_source IN ('sdk','computed')),
  created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX agent_usage_created ON agent_usage (created_at);
CREATE INDEX agent_usage_model_created ON agent_usage (model, created_at);
