-- migrate:up

-- Incremental one-page polls are not full-board scrapes, so the old
-- multi-hour floors would block the 30-minute cadence.
UPDATE sources SET min_interval = interval '15 minutes'
WHERE id IN ('linkedin_guest', 'indeed', 'glassdoor');

INSERT INTO sources (id, kind, min_interval, close_after) VALUES
  ('seek', 'aggregator', interval '15 minutes', interval '14 days');

ALTER TABLE runs DROP CONSTRAINT IF EXISTS runs_status_check;
ALTER TABLE runs ADD CONSTRAINT runs_status_check
  CHECK (status IN ('running', 'ok', 'partial', 'failed', 'skipped'));
ALTER TABLE runs ADD COLUMN search_id bigint;
ALTER TABLE runs ADD COLUMN skipped int NOT NULL DEFAULT 0;

ALTER TABLE postings ADD COLUMN detail_status text NOT NULL DEFAULT 'done'
  CHECK (detail_status IN ('pending', 'done', 'failed'));
ALTER TABLE postings ADD COLUMN detail_attempts int NOT NULL DEFAULT 0;
CREATE INDEX postings_detail_pending ON postings (first_seen_at)
  WHERE detail_status = 'pending';

CREATE TABLE searches (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name        text NOT NULL,
  keywords    text[] NOT NULL,
  countries   char(2)[] NOT NULL,
  timezone    text NOT NULL DEFAULT 'Asia/Bangkok',
  enabled     boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE search_sources (
  search_id        bigint NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
  source_id        text NOT NULL REFERENCES sources(id),
  poll_minutes     int NOT NULL DEFAULT 30,
  paused_until     timestamptz,
  strikes          int NOT NULL DEFAULT 0,
  enabled          boolean NOT NULL DEFAULT true,
  last_catchup_at  timestamptz,
  cursor           jsonb,
  PRIMARY KEY (search_id, source_id)
);

ALTER TABLE runs
  ADD CONSTRAINT runs_search_id_fkey
  FOREIGN KEY (search_id) REFERENCES searches(id) ON DELETE SET NULL;

CREATE TABLE search_markets (
  search_id       bigint NOT NULL,
  source_id       text NOT NULL,
  country         char(2) NOT NULL,
  last_polled_at  timestamptz,
  last_status     text,
  PRIMARY KEY (search_id, source_id, country),
  FOREIGN KEY (search_id, source_id)
    REFERENCES search_sources (search_id, source_id) ON DELETE CASCADE
);

CREATE TABLE scrape_settings (
  id             boolean PRIMARY KEY DEFAULT true CHECK (id),
  allowed_roles  text[] NOT NULL
);

INSERT INTO scrape_settings (allowed_roles) VALUES
  (ARRAY['software', 'fullstack', 'frontend', 'backend', 'ml']);

CREATE TABLE tick_hooks (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name         text NOT NULL,
  phase        text NOT NULL,
  exit_code    int,
  duration_ms  int NOT NULL,
  ran_at       timestamptz NOT NULL DEFAULT now(),
  error        text
);

INSERT INTO searches (name, keywords, countries, timezone) VALUES (
  'Software roles',
  ARRAY['Fullstack', 'Software Engineer', 'Frontend', 'Backend', 'AI Engineer', 'AI-augmented Engineer'],
  ARRAY['TH','SG','TW','JP','AU','NZ','HK','MY','VN','ID','PH','IN','GB','DE','NL','FR'],
  'Asia/Bangkok'
);

INSERT INTO search_sources (search_id, source_id, poll_minutes)
SELECT s.id, src.source_id, src.poll_minutes
FROM searches s
CROSS JOIN (VALUES
  ('linkedin_guest', 30),
  ('seek', 30),
  ('indeed', 720),
  ('glassdoor', 720),
  ('adzuna', 1440),
  ('reed', 1440),
  ('jooble', 1440),
  ('mycareersfuture', 1440),
  ('naukri', 1440)
) AS src(source_id, poll_minutes)
WHERE s.name = 'Software roles';

-- Aggregator collection moves to searches. Leave ATS scopes on their cron.
UPDATE fetch_scopes SET enabled = false
WHERE source_id NOT IN ('greenhouse', 'lever', 'ashby');

-- migrate:down

UPDATE fetch_scopes SET enabled = true
WHERE source_id NOT IN ('greenhouse', 'lever', 'ashby');

DELETE FROM searches WHERE name = 'Software roles';
DROP TABLE tick_hooks;
DROP TABLE search_markets;
ALTER TABLE runs DROP CONSTRAINT IF EXISTS runs_search_id_fkey;
DROP TABLE search_sources;
DROP TABLE searches;
DROP TABLE scrape_settings;
ALTER TABLE postings DROP COLUMN detail_attempts;
ALTER TABLE postings DROP COLUMN detail_status;
ALTER TABLE runs DROP COLUMN skipped;
ALTER TABLE runs DROP COLUMN search_id;
ALTER TABLE runs DROP CONSTRAINT IF EXISTS runs_status_check;
ALTER TABLE runs ADD CONSTRAINT runs_status_check
  CHECK (status IN ('running', 'ok', 'partial', 'failed'));
DELETE FROM sources WHERE id = 'seek';
UPDATE sources SET min_interval = interval '12 hours' WHERE id = 'linkedin_guest';
UPDATE sources SET min_interval = interval '6 hours' WHERE id = 'indeed';
UPDATE sources SET min_interval = interval '24 hours' WHERE id = 'glassdoor';
