-- migrate:up

ALTER TABLE jobs ADD COLUMN role text;
ALTER TABLE jobs ADD COLUMN industry text;
CREATE INDEX jobs_role ON jobs (role) WHERE closed_at IS NULL AND role IS NOT NULL;
CREATE INDEX jobs_industry ON jobs (industry) WHERE closed_at IS NULL AND industry IS NOT NULL;

-- migrate:down

DROP INDEX IF EXISTS jobs_industry;
DROP INDEX IF EXISTS jobs_role;
ALTER TABLE jobs DROP COLUMN industry;
ALTER TABLE jobs DROP COLUMN role;
