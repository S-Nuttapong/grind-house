-- migrate:up

ALTER TABLE agent_usage ADD COLUMN purpose text;
UPDATE agent_usage SET purpose = 'resume' WHERE purpose IS NULL;
ALTER TABLE agent_usage ALTER COLUMN purpose SET NOT NULL;
ALTER TABLE agent_usage ALTER COLUMN purpose SET DEFAULT 'resume';
ALTER TABLE agent_usage ADD CONSTRAINT agent_usage_purpose_check CHECK (purpose IN ('fit', 'facts', 'resume'));
ALTER TABLE agent_usage ALTER COLUMN run_id DROP NOT NULL;
ALTER TABLE agent_usage ADD COLUMN job_id bigint REFERENCES jobs(id) ON DELETE SET NULL;
ALTER TABLE agent_usage ADD COLUMN success boolean NOT NULL DEFAULT true;
ALTER TABLE agent_usage ADD COLUMN error text;

-- migrate:down

ALTER TABLE agent_usage DROP CONSTRAINT IF EXISTS agent_usage_purpose_check;
ALTER TABLE agent_usage DROP COLUMN IF EXISTS error;
ALTER TABLE agent_usage DROP COLUMN IF EXISTS success;
ALTER TABLE agent_usage DROP COLUMN IF EXISTS job_id;
ALTER TABLE agent_usage DROP COLUMN IF EXISTS purpose;
DELETE FROM agent_usage WHERE run_id IS NULL;
ALTER TABLE agent_usage ALTER COLUMN run_id SET NOT NULL;
