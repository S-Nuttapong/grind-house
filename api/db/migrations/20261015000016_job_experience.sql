-- migrate:up

-- Nullable years asked for by the posting. Adding columns is safe for the running app.
ALTER TABLE jobs ADD COLUMN experience_min_years smallint
  CHECK (experience_min_years BETWEEN 0 AND 20);
ALTER TABLE jobs ADD COLUMN experience_max_years smallint
  CHECK (experience_max_years BETWEEN 0 AND 20);
ALTER TABLE jobs ADD CONSTRAINT jobs_experience_order CHECK (
  experience_max_years IS NULL
  OR experience_min_years IS NULL
  OR experience_max_years >= experience_min_years
);
CREATE INDEX jobs_experience_min ON jobs (experience_min_years)
  WHERE closed_at IS NULL AND experience_min_years IS NOT NULL;

-- migrate:down

DROP INDEX IF EXISTS jobs_experience_min;
ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_experience_order;
ALTER TABLE jobs DROP COLUMN IF EXISTS experience_max_years;
ALTER TABLE jobs DROP COLUMN IF EXISTS experience_min_years;
