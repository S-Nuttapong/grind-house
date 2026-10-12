-- migrate:up

INSERT INTO sources (id, kind, min_interval, close_after) VALUES
  ('naukri', 'aggregator', interval '24 hours', interval '14 days'),
  ('adzuna', 'aggregator', interval '24 hours', interval '14 days'),
  ('reed', 'aggregator', interval '24 hours', interval '14 days'),
  ('jooble', 'aggregator', interval '24 hours', interval '14 days'),
  ('mycareersfuture', 'feed', interval '12 hours', interval '21 days');

-- migrate:down

DELETE FROM sources WHERE id IN (
  'naukri', 'adzuna', 'reed', 'jooble', 'mycareersfuture'
);
