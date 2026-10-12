-- migrate:up

-- ───────────── Profile (brag bank + resumes) ─────────────

CREATE TABLE bank_entries (                            -- one row per brag-bank entry
  id            text PRIMARY KEY,                      -- 'BB-001'
  title         text NOT NULL,
  company       text,
  role          text,
  period        text,
  my_role       text CHECK (my_role IN ('led','built','co-built','contributed')),
  scope         text,
  metrics       jsonb NOT NULL DEFAULT '[]',
  strength      smallint CHECK (strength BETWEEN 1 AND 5),
  confidential  boolean NOT NULL DEFAULT false,
  status        text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','needs-metric','verified')),
  tags          text[] NOT NULL DEFAULT '{}',
  body_md       text NOT NULL DEFAULT '',
  origin        text NOT NULL DEFAULT 'ui' CHECK (origin IN ('vault','ui')),
  updated_at    timestamptz NOT NULL DEFAULT now()
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
  matched_terms  text[] NOT NULL DEFAULT '{}',
  missing_terms  text[] NOT NULL DEFAULT '{}',
  computed_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (job_id, model_id, source_hash)
);
CREATE INDEX job_fits_rank ON job_fits (source_hash, model_id, score DESC);

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

-- migrate:down

DROP TABLE IF EXISTS fit_run_events;
DROP TABLE IF EXISTS fit_runs;
DROP TABLE IF EXISTS fit_schedules;
DROP TABLE IF EXISTS fit_worker;
DROP TABLE IF EXISTS job_fits;
DROP TABLE IF EXISTS fit_sources;
DROP TABLE IF EXISTS resumes;
DROP TABLE IF EXISTS bank_profile;
DROP TABLE IF EXISTS bank_entries;
