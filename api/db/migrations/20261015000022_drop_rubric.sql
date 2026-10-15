-- migrate:up

DROP TABLE IF EXISTS match_criteria;
DROP TABLE IF EXISTS rule_hits;
DROP TABLE IF EXISTS matches;
DROP TABLE IF EXISTS prefilter;
DROP TABLE IF EXISTS requirements;
DROP TABLE IF EXISTS rules;
DROP TABLE IF EXISTS profiles;

-- migrate:down

CREATE TABLE profiles (
  hash        text PRIMARY KEY,
  profile     jsonb NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE requirements (
  job_id          bigint NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  prompt_version  text NOT NULL,
  model           text NOT NULL,
  extracted       jsonb NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (job_id, prompt_version)
);

CREATE TABLE prefilter (
  job_id         bigint PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
  profile_hash   text NOT NULL REFERENCES profiles(hash),
  passed_hard    boolean NOT NULL,
  filter_reason  text,
  score          real,
  shortlisted    boolean NOT NULL DEFAULT false,
  computed_at    timestamptz NOT NULL DEFAULT now(),
  CHECK (passed_hard OR (score IS NULL AND NOT shortlisted)),
  CHECK (passed_hard OR filter_reason IS NOT NULL)
);
CREATE INDEX prefilter_shortlist ON prefilter (score DESC) WHERE shortlisted;

CREATE TABLE matches (
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

CREATE TABLE match_criteria (
  match_id     bigint NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
  ordinal      smallint NOT NULL,
  criterion    text NOT NULL CHECK (criterion IN ('must_have','level','stack','domain','logistics')),
  requirement  text NOT NULL,
  jd_quote     text,
  label        text NOT NULL CHECK (label IN ('met','adjacent','gap','unknown')),
  evidence     text[] NOT NULL DEFAULT '{}',
  evidence_ok  boolean NOT NULL DEFAULT false,
  note         text,
  PRIMARY KEY (match_id, ordinal),
  CHECK (label NOT IN ('met','adjacent') OR cardinality(evidence) > 0)
);
CREATE INDEX match_criteria_gaps ON match_criteria (criterion, requirement) WHERE label = 'gap';

CREATE TABLE rules (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name              text NOT NULL,
  filters           jsonb NOT NULL,
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
