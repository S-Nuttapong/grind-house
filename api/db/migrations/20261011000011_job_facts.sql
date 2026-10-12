-- migrate:up

ALTER TABLE jobs ADD COLUMN locations jsonb NOT NULL DEFAULT '[]';
ALTER TABLE jobs ADD COLUMN countries char(2)[] NOT NULL DEFAULT '{}';
ALTER TABLE jobs ADD COLUMN fact_origins jsonb NOT NULL DEFAULT '{}';
ALTER TABLE jobs DROP CONSTRAINT jobs_employment_type_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_employment_type_check
  CHECK (employment_type IS NULL OR employment_type IN ('fulltime','parttime','contract','internship','temporary'));
ALTER TABLE postings ADD COLUMN facts jsonb;
ALTER TABLE postings ADD COLUMN facts_status text NOT NULL DEFAULT 'done'
  CHECK (facts_status IN ('pending','done'));
CREATE INDEX jobs_countries ON jobs USING gin (countries);
CREATE INDEX postings_facts_pending ON postings (id) WHERE facts_status = 'pending';

-- migrate:down

DROP INDEX IF EXISTS postings_facts_pending;
DROP INDEX IF EXISTS jobs_countries;
ALTER TABLE postings DROP COLUMN IF EXISTS facts_status;
ALTER TABLE postings DROP COLUMN IF EXISTS facts;
ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_employment_type_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_employment_type_check
  CHECK (employment_type IS NULL OR employment_type IN ('fulltime','parttime','contract','internship'));
ALTER TABLE jobs DROP COLUMN IF EXISTS fact_origins;
ALTER TABLE jobs DROP COLUMN IF EXISTS countries;
ALTER TABLE jobs DROP COLUMN IF EXISTS locations;
