-- migrate:up

-- 'removed' takes a job off the pipeline without deleting its history.
ALTER TABLE job_events DROP CONSTRAINT job_events_status_check;
ALTER TABLE job_events ADD CONSTRAINT job_events_status_check
  CHECK (status IN ('saved','skipped','applied','screening','interviewing','offer','rejected','withdrawn','removed'));

CREATE OR REPLACE VIEW job_status AS
  SELECT job_id, status, at FROM (
    SELECT DISTINCT ON (job_id) job_id, status, at
    FROM job_events ORDER BY job_id, at DESC
  ) latest
  WHERE status <> 'removed';

-- migrate:down

DELETE FROM job_events WHERE status = 'removed';

DROP VIEW job_status;
CREATE VIEW job_status AS
  SELECT DISTINCT ON (job_id) job_id, status, at
  FROM job_events ORDER BY job_id, at DESC;

ALTER TABLE job_events DROP CONSTRAINT job_events_status_check;
ALTER TABLE job_events ADD CONSTRAINT job_events_status_check
  CHECK (status IN ('saved','skipped','applied','screening','interviewing','offer','rejected','withdrawn'));
