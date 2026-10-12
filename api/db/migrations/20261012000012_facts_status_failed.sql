-- migrate:up

ALTER TABLE postings DROP CONSTRAINT postings_facts_status_check;
ALTER TABLE postings ADD CONSTRAINT postings_facts_status_check
  CHECK (facts_status IN ('pending', 'done', 'failed'));

-- migrate:down

ALTER TABLE postings DROP CONSTRAINT postings_facts_status_check;
ALTER TABLE postings ADD CONSTRAINT postings_facts_status_check
  CHECK (facts_status IN ('pending', 'done'));
