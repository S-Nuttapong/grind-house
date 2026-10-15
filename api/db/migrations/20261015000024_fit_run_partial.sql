-- migrate:up

ALTER TABLE fit_runs DROP CONSTRAINT IF EXISTS fit_runs_status_check;
ALTER TABLE fit_runs ADD CONSTRAINT fit_runs_status_check
  CHECK (status IN ('queued', 'running', 'ok', 'failed', 'partial'));

-- migrate:down

UPDATE fit_runs SET status = 'failed' WHERE status = 'partial';
ALTER TABLE fit_runs DROP CONSTRAINT IF EXISTS fit_runs_status_check;
ALTER TABLE fit_runs ADD CONSTRAINT fit_runs_status_check
  CHECK (status IN ('queued', 'running', 'ok', 'failed'));
