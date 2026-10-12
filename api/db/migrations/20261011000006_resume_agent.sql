-- migrate:up

-- Impact ranks brag docs used to fill a one-page resume. See ADR-0005.

ALTER TABLE brag_docs ADD COLUMN impact smallint CHECK (impact BETWEEN 1 AND 5);

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
  attempts            integer NOT NULL DEFAULT 0,
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

-- migrate:down

DROP TABLE IF EXISTS agent_usage;
DROP TABLE IF EXISTS resume_artifacts;
DROP TABLE IF EXISTS resume_run_events;
DROP TABLE IF EXISTS resume_runs;
ALTER TABLE brag_docs DROP COLUMN IF EXISTS impact;
