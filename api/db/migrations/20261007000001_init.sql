-- migrate:up

-- Job Hunt OS schema · Postgres 16+ · v0.4
-- Relational core, JSONB only where the shape varies (source params, raw payloads, LLM output, filters).

CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- fuzzy title match for dedupe and search

-- ───────────── Reference ─────────────

CREATE TABLE sources (
  id            text PRIMARY KEY,                       -- 'greenhouse', 'linkedin_guest'
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
  status           text NOT NULL DEFAULT 'running' CHECK (status IN ('running','ok','partial','failed')),
  fetched          int NOT NULL DEFAULT 0,
  new_jobs         int NOT NULL DEFAULT 0,
  updated          int NOT NULL DEFAULT 0,
  closed           int NOT NULL DEFAULT 0,
  error            text,
  scraper_version  text NOT NULL
);
CREATE INDEX runs_source_started ON runs (source_id, started_at DESC);

-- ───────────── Jobs ─────────────

CREATE TABLE jobs (                                     -- one row per real job (canonical)
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  company_id       bigint NOT NULL REFERENCES companies(id),
  title            text NOT NULL,
  title_norm       text NOT NULL,
  level            text NOT NULL DEFAULT 'unknown'
                   CHECK (level IN ('intern','junior','mid','senior','staff','principal','lead','manager','unknown')),
  country          char(2),                             -- ISO 3166-1 alpha-2
  city             text,
  remote           text NOT NULL DEFAULT 'unknown' CHECK (remote IN ('onsite','hybrid','remote','unknown')),
  tz_min           smallint CHECK (tz_min BETWEEN -12 AND 14),   -- allowed UTC offsets for remote roles
  tz_max           smallint CHECK (tz_max BETWEEN -12 AND 14),
  employment_type  text CHECK (employment_type IN ('fulltime','parttime','contract','internship')),
  salary_min       numeric(12,0),
  salary_max       numeric(12,0),
  salary_currency  char(3),
  salary_interval  text CHECK (salary_interval IN ('yearly','monthly','weekly','daily','hourly')),
  salary_usd_year_min numeric(12,0),                    -- normalized by the app for filtering
  posted_at        date,
  first_seen_at    timestamptz NOT NULL DEFAULT now(),
  last_seen_at     timestamptz NOT NULL DEFAULT now(),
  closed_at        timestamptz,
  apply_url        text NOT NULL,                       -- prefers the company ATS over aggregator links
  description_md   text,                                -- dropped by retention for old, untouched jobs
  dedupe_key       text NOT NULL,                       -- company_id|title_norm|country
  search           tsvector GENERATED ALWAYS AS (
                     setweight(to_tsvector('english', coalesce(title,'')), 'A') ||
                     setweight(to_tsvector('english', coalesce(description_md,'')), 'B')
                   ) STORED,
  CHECK (salary_max IS NULL OR salary_min IS NULL OR salary_max >= salary_min)
);
CREATE INDEX jobs_open       ON jobs (posted_at DESC) WHERE closed_at IS NULL;
CREATE INDEX jobs_place      ON jobs (country, remote) WHERE closed_at IS NULL;
CREATE INDEX jobs_dedupe     ON jobs (dedupe_key);
CREATE INDEX jobs_company    ON jobs (company_id);
CREATE INDEX jobs_search     ON jobs USING gin (search);
CREATE INDEX jobs_title_trgm ON jobs USING gin (title_norm gin_trgm_ops);

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
  UNIQUE (source_id, source_job_id)
);
CREATE INDEX postings_job ON postings (job_id);

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
  status   text NOT NULL CHECK (status IN ('saved','skipped','applied','screening','interviewing','offer','rejected','withdrawn')),
  reason   text,                                        -- skip reason feeds calibration
  note     text,
  origin   text NOT NULL DEFAULT 'ui' CHECK (origin IN ('ui','claude','gmail')),
  at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX job_events_job ON job_events (job_id, at DESC);

CREATE VIEW job_status AS
  SELECT DISTINCT ON (job_id) job_id, status, at
  FROM job_events ORDER BY job_id, at DESC;

CREATE TABLE labels (                                   -- calibration ground truth
  job_id      bigint PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
  label       text NOT NULL CHECK (label IN ('apply','maybe','skip')),
  origin      text NOT NULL CHECK (origin IN ('calibration','ui_action')),
  labeled_at  timestamptz NOT NULL DEFAULT now()
);

-- migrate:down

DROP VIEW IF EXISTS job_status;
DROP TABLE IF EXISTS labels;
DROP TABLE IF EXISTS job_events;
DROP TABLE IF EXISTS rule_hits;
DROP TABLE IF EXISTS rules;
DROP TABLE IF EXISTS match_criteria;
DROP TABLE IF EXISTS matches;
DROP TABLE IF EXISTS prefilter;
DROP TABLE IF EXISTS requirements;
DROP TABLE IF EXISTS profiles;
DROP TABLE IF EXISTS raw_payloads;
DROP TABLE IF EXISTS postings;
DROP TABLE IF EXISTS jobs;
DROP TABLE IF EXISTS runs;
DROP TABLE IF EXISTS fetch_scopes;
DROP TABLE IF EXISTS company_aliases;
DROP TABLE IF EXISTS companies;
DROP TABLE IF EXISTS sources;
DROP EXTENSION IF EXISTS pg_trgm;
