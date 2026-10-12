-- migrate:up

-- The fit worker compares a job's current text to the hash stored at scoring
-- time. digest() is the same sha256 Python stores on job_fits.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- migrate:down

DROP EXTENSION IF EXISTS pgcrypto;
