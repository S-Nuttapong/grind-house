-- migrate:up

-- Manual order within a pipeline column. A missing rank sorts with the newest status first.
CREATE TABLE pipeline_ranks (
  job_id  bigint PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
  rank    integer NOT NULL
);

-- migrate:down

DROP TABLE IF EXISTS pipeline_ranks;
