-- migrate:up

-- A 404 means the posting was taken down. 'gone' keeps the backfill from
-- queueing it again. Adding a value is safe for the running app.
ALTER TABLE postings DROP CONSTRAINT postings_detail_status_check;
ALTER TABLE postings ADD CONSTRAINT postings_detail_status_check
  CHECK (detail_status IN ('pending', 'done', 'failed', 'gone'));

-- migrate:down

UPDATE postings SET detail_status = 'failed' WHERE detail_status = 'gone';
ALTER TABLE postings DROP CONSTRAINT postings_detail_status_check;
ALTER TABLE postings ADD CONSTRAINT postings_detail_status_check
  CHECK (detail_status IN ('pending', 'done', 'failed'));
