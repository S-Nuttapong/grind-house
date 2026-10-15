-- migrate:up

ALTER TABLE pipeline_ranks RENAME TO tracker_ranks;

-- migrate:down

ALTER TABLE tracker_ranks RENAME TO pipeline_ranks;
