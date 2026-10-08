-- migrate:up

INSERT INTO sources (id, kind, min_interval, close_after) VALUES
  ('greenhouse', 'ats', interval '6 hours', NULL),
  ('lever', 'ats', interval '6 hours', NULL),
  ('ashby', 'ats', interval '6 hours', NULL),
  ('indeed', 'aggregator', interval '6 hours', interval '14 days'),
  ('linkedin_guest', 'aggregator', interval '12 hours', interval '14 days'),
  ('glassdoor', 'aggregator', interval '24 hours', interval '14 days'),
  ('ziprecruiter', 'aggregator', interval '24 hours', interval '14 days'),
  ('hn', 'feed', interval '24 hours', interval '45 days'),
  ('remoteok', 'feed', interval '12 hours', interval '21 days'),
  ('remotive', 'feed', interval '12 hours', interval '21 days');

-- migrate:down

DELETE FROM sources WHERE id IN (
  'greenhouse', 'lever', 'ashby', 'indeed', 'linkedin_guest',
  'glassdoor', 'ziprecruiter', 'hn', 'remoteok', 'remotive'
);
