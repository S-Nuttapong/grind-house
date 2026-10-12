-- migrate:up

-- Matrix fit stores coverage and the brag docs selected for each job.
-- See ADR-0004.

ALTER TABLE job_fits ADD COLUMN coverage real;
ALTER TABLE job_fits ADD COLUMN gaps text[] NOT NULL DEFAULT '{}';

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

-- migrate:down

DROP TABLE IF EXISTS job_fit_matches;
ALTER TABLE job_fits DROP COLUMN IF EXISTS gaps;
ALTER TABLE job_fits DROP COLUMN IF EXISTS coverage;
