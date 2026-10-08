-- migrate:up

-- Brag docs replace bank_entries. See ADR-0002.

CREATE TABLE tags (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name       text NOT NULL,
  color_hex  text NOT NULL CHECK (color_hex ~ '^#[0-9A-Fa-f]{6}$')
);
CREATE UNIQUE INDEX tags_name_lower ON tags (lower(name));

CREATE TABLE metric_keys (
  id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name  text NOT NULL
);
CREATE UNIQUE INDEX metric_keys_name_lower ON metric_keys (lower(name));

CREATE TABLE brag_docs (
  id              text PRIMARY KEY,
  title           text NOT NULL,
  date            date NOT NULL,
  quarter         text GENERATED ALWAYS AS (
                    'Q' || extract(quarter FROM date)::int::text
                    || ' ' || extract(year FROM date)::int::text
                  ) STORED,
  company         text,
  role            text,
  description_md  text NOT NULL DEFAULT '',
  origin          text NOT NULL DEFAULT 'ui' CHECK (origin IN ('vault','ui')),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE brag_doc_tags (
  brag_doc_id  text NOT NULL REFERENCES brag_docs(id) ON DELETE CASCADE,
  tag_id       bigint NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  PRIMARY KEY (brag_doc_id, tag_id)
);

CREATE TABLE brag_doc_metrics (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  brag_doc_id     text NOT NULL REFERENCES brag_docs(id) ON DELETE CASCADE,
  metric_key_id   bigint NOT NULL REFERENCES metric_keys(id) ON DELETE RESTRICT,
  value           text NOT NULL,
  position        integer NOT NULL
);

CREATE TABLE brag_doc_attachments (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  brag_doc_id  text NOT NULL REFERENCES brag_docs(id) ON DELETE CASCADE,
  type         text NOT NULL CHECK (type IN ('url')),
  link         text NOT NULL CHECK (link ~ '^https?://'),
  position     integer NOT NULL
);

INSERT INTO brag_docs (id, title, date, company, role, description_md, origin, updated_at)
SELECT
  bank_entries.id,
  bank_entries.title,
  COALESCE(end_of_period.day, bank_entries.updated_at::date),
  bank_entries.company,
  bank_entries.role,
  bank_entries.body_md,
  bank_entries.origin,
  bank_entries.updated_at
FROM bank_entries
LEFT JOIN LATERAL (
  SELECT (
    date_trunc('month', make_date(parsed.year, parsed.month, 1))
    + interval '1 month' - interval '1 day'
  )::date AS day
  FROM (
    SELECT match[1]::int AS year, match[2]::int AS month
    FROM regexp_matches(coalesce(bank_entries.period, ''), '([0-9]{4})-([0-9]{2})', 'g') AS match
  ) parsed
  WHERE parsed.month BETWEEN 1 AND 12 AND parsed.year BETWEEN 1900 AND 2200
  ORDER BY parsed.year DESC, parsed.month DESC
  LIMIT 1
) end_of_period ON true;

INSERT INTO tags (name, color_hex)
SELECT DISTINCT
  tag_name,
  (ARRAY[
    '#3B82F6', '#10B981', '#F59E0B', '#EF4444',
    '#8B5CF6', '#EC4899', '#14B8A6', '#F97316'
  ])[1 + ((hashtext(lower(tag_name)) % 8 + 8) % 8)]
FROM bank_entries
CROSS JOIN LATERAL unnest(bank_entries.tags) AS tag_name
WHERE tag_name <> '';

INSERT INTO brag_doc_tags (brag_doc_id, tag_id)
SELECT bank_entries.id, tags.id
FROM bank_entries
CROSS JOIN LATERAL unnest(bank_entries.tags) AS tag_name
JOIN tags ON lower(tags.name) = lower(tag_name);

INSERT INTO metric_keys (name)
SELECT DISTINCT
  COALESCE(
    NULLIF(initcap(replace(replace(item->>'kind', '_', ' '), '-', ' ')), ''),
    'General'
  )
FROM bank_entries
CROSS JOIN LATERAL jsonb_array_elements(bank_entries.metrics) AS item
WHERE jsonb_typeof(item) = 'object';

INSERT INTO brag_doc_metrics (brag_doc_id, metric_key_id, value, position)
SELECT bank_entries.id, metric_keys.id, COALESCE(metric.item->>'text', ''), metric.ordinality::int
FROM bank_entries
CROSS JOIN LATERAL jsonb_array_elements(bank_entries.metrics)
  WITH ORDINALITY AS metric(item, ordinality)
JOIN metric_keys ON lower(metric_keys.name) = lower(
  COALESCE(
    NULLIF(initcap(replace(replace(metric.item->>'kind', '_', ' '), '-', ' ')), ''),
    'General'
  )
)
WHERE jsonb_typeof(metric.item) = 'object';

DROP TABLE bank_entries;

-- migrate:down

DROP TABLE IF EXISTS brag_doc_attachments;
DROP TABLE IF EXISTS brag_doc_metrics;
DROP TABLE IF EXISTS brag_doc_tags;
DROP TABLE IF EXISTS brag_docs;
DROP TABLE IF EXISTS metric_keys;
DROP TABLE IF EXISTS tags;

CREATE TABLE bank_entries (
  id            text PRIMARY KEY,
  title         text NOT NULL,
  company       text,
  role          text,
  period        text,
  my_role       text CHECK (my_role IN ('led','built','co-built','contributed')),
  scope         text,
  metrics       jsonb NOT NULL DEFAULT '[]',
  strength      smallint CHECK (strength BETWEEN 1 AND 5),
  confidential  boolean NOT NULL DEFAULT false,
  status        text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','needs-metric','verified')),
  tags          text[] NOT NULL DEFAULT '{}',
  body_md       text NOT NULL DEFAULT '',
  origin        text NOT NULL DEFAULT 'ui' CHECK (origin IN ('vault','ui')),
  updated_at    timestamptz NOT NULL DEFAULT now()
);
