-- migrate:up

-- Domains: one definition per rule. The domain allows NULL; NOT NULL stays on the column.
CREATE DOMAIN currency_code AS text CHECK (VALUE ~ '^[A-Z]{3}$');
CREATE DOMAIN money_amount AS numeric CHECK (VALUE > 0);
CREATE DOMAIN months AS smallint CHECK (VALUE BETWEEN 0 AND 600);

COMMENT ON DOMAIN currency_code IS 'ISO 4217 alphabetic code.';
COMMENT ON DOMAIN money_amount IS 'Exact amount, greater than zero. Never the money type.';
COMMENT ON DOMAIN months IS 'Experience in months. 0 means none required. 600 is 50 years.';

CREATE TABLE fx_rates (
  currency     currency_code PRIMARY KEY,
  usd_per_unit numeric NOT NULL CHECK (usd_per_unit > 0),
  as_of        date NOT NULL,
  source       text NOT NULL CHECK (source IN ('frankfurter', 'open_er_api')),
  fetched_at   timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE fx_rates IS 'USD per 1 unit of currency. Frankfurter wins; open.er-api fills currencies it lacks.';
COMMENT ON COLUMN fx_rates.usd_per_unit IS 'Multiply a local amount by this to get USD.';
COMMENT ON COLUMN fx_rates.as_of IS 'The rate date reported by the provider.';

CREATE TABLE job_compensation (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  job_id         bigint NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  type           text NOT NULL CHECK (type IN (
                   'base', 'bonus', 'signing_bonus', 'equity',
                   'profit_sharing', 'commission', 'tips', 'other')),
  unit           text CHECK (unit IN ('hourly', 'daily', 'weekly', 'monthly', 'yearly', 'one_time')),
  currency       currency_code NOT NULL,
  min_amount     money_amount,
  max_amount     money_amount,
  units_per_year numeric CHECK (units_per_year > 0),
  annual_min     numeric GENERATED ALWAYS AS (COALESCE(min_amount, max_amount) * units_per_year) STORED,
  annual_max     numeric GENERATED ALWAYS AS (COALESCE(max_amount, min_amount) * units_per_year) STORED,
  evidence       text CHECK (evidence <> ''),
  parser_id      text NOT NULL,
  updated_at     timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT job_compensation_has_amount CHECK (min_amount IS NOT NULL OR max_amount IS NOT NULL),
  CONSTRAINT job_compensation_order CHECK (max_amount >= min_amount),
  CONSTRAINT job_compensation_unit_year CHECK ((unit IS NULL) = (units_per_year IS NULL)),
  CONSTRAINT job_compensation_base_unit CHECK (type <> 'base' OR unit <> 'one_time'),
  CONSTRAINT job_compensation_evidence CHECK (evidence IS NOT NULL OR parser_id LIKE 'api:%')
);

CREATE UNIQUE INDEX job_compensation_one_base ON job_compensation (job_id) WHERE type = 'base';

COMMENT ON TABLE job_compensation IS 'One row per pay component. At most one base row per job.';
COMMENT ON COLUMN job_compensation.min_amount IS 'Inclusive lower bound. NULL means the posting stated no minimum.';
COMMENT ON COLUMN job_compensation.max_amount IS 'Inclusive upper bound. NULL means the posting stated no maximum.';
COMMENT ON COLUMN job_compensation.units_per_year IS
  'CTS defaults: hourly 2080, daily 260, weekly 52, monthly 12, yearly 1. NULL when unit is NULL.';
COMMENT ON COLUMN job_compensation.evidence IS 'Verbatim posting text. NULL only for board API rows (parser_id api:%).';

CREATE VIEW job_base_pay AS
SELECT c.job_id, c.currency, c.unit, c.min_amount, c.max_amount, c.units_per_year,
       c.annual_min, c.annual_max,
       round(c.annual_min * fx.usd_per_unit) AS usd_annual_min,
       round(c.annual_max * fx.usd_per_unit) AS usd_annual_max,
       fx.as_of AS fx_as_of,
       c.evidence, c.parser_id
FROM job_compensation c
LEFT JOIN fx_rates fx ON fx.currency = c.currency
WHERE c.type = 'base';

COMMENT ON VIEW job_base_pay IS 'Base pay with USD computed at read time from fx_rates.';

-- copy:begin
INSERT INTO job_compensation (
  job_id, type, unit, currency, min_amount, max_amount, units_per_year, evidence, parser_id
)
SELECT
  j.id,
  'base',
  j.salary_interval,
  upper(btrim(j.salary_currency::text)),
  CASE WHEN j.salary_min > 0 THEN j.salary_min END,
  CASE WHEN j.salary_max > 0 THEN j.salary_max END,
  CASE j.salary_interval
    WHEN 'hourly' THEN 2080
    WHEN 'daily' THEN 260
    WHEN 'weekly' THEN 52
    WHEN 'monthly' THEN 12
    WHEN 'yearly' THEN 1
  END,
  NULLIF(btrim(pay.evidence), ''),
  COALESCE(NULLIF(j.fact_origins->>'pay', ''), 'migrated')
FROM jobs j
LEFT JOIN LATERAL (
  SELECT p.facts->'pay'->>'evidence' AS evidence
  FROM postings p
  WHERE p.job_id = j.id
    AND NULLIF(btrim(p.facts->'pay'->>'evidence'), '') IS NOT NULL
  ORDER BY p.id
  LIMIT 1
) pay ON true
WHERE (j.salary_min > 0 OR j.salary_max > 0)
  AND upper(btrim(j.salary_currency::text)) ~ '^[A-Z]{3}$'
  AND (
    COALESCE(j.fact_origins->>'pay', '') LIKE 'api:%'
    OR NULLIF(btrim(pay.evidence), '') IS NOT NULL
  );
-- copy:end

DO $$
DECLARE
  pay_rows bigint;
  copied bigint;
  skipped bigint;
BEGIN
  SELECT count(*) INTO pay_rows FROM jobs WHERE salary_min > 0 OR salary_max > 0;
  SELECT count(*) INTO copied FROM job_compensation WHERE type = 'base';
  skipped := pay_rows - copied;
  RAISE NOTICE 'job_compensation copy: % base rows, % jobs with pay skipped', copied, skipped;
END $$;

ALTER TABLE jobs ADD COLUMN experience_min_months months;
ALTER TABLE jobs ADD COLUMN experience_max_months months;
ALTER TABLE jobs ADD CONSTRAINT jobs_experience_months_order
  CHECK (experience_max_months >= experience_min_months);
ALTER TABLE jobs ADD CONSTRAINT jobs_experience_months_has_min
  CHECK (experience_max_months IS NULL OR experience_min_months IS NOT NULL);
CREATE INDEX jobs_experience_months_min ON jobs (experience_min_months) WHERE closed_at IS NULL;

COMMENT ON COLUMN jobs.experience_min_months IS '0 means the posting requires no experience. NULL means not stated.';
COMMENT ON COLUMN jobs.experience_max_months IS 'NULL means no stated upper bound.';

UPDATE jobs
SET experience_min_months = experience_min_years * 12,
    experience_max_months = experience_max_years * 12
WHERE experience_min_years IS NOT NULL OR experience_max_years IS NOT NULL;

-- Rates as of 2026-10-14 so USD works before the first sync. Frankfurter, except VND.
INSERT INTO fx_rates (currency, usd_per_unit, as_of, source) VALUES
  ('USD', 1.0, '2026-10-14', 'frankfurter'),
  ('AUD', 0.700967, '2026-10-14', 'frankfurter'),
  ('CAD', 0.703284, '2026-10-14', 'frankfurter'),
  ('CHF', 1.199890, '2026-10-14', 'frankfurter'),
  ('EUR', 1.119495, '2026-10-14', 'frankfurter'),
  ('GBP', 1.326665, '2026-10-14', 'frankfurter'),
  ('HKD', 0.127419, '2026-10-14', 'frankfurter'),
  ('IDR', 0.000056, '2026-10-14', 'frankfurter'),
  ('INR', 0.010509, '2026-10-14', 'frankfurter'),
  ('JPY', 0.006311, '2026-10-14', 'frankfurter'),
  ('MYR', 0.244948, '2026-10-14', 'frankfurter'),
  ('NZD', 0.561419, '2026-10-14', 'frankfurter'),
  ('PHP', 0.015904, '2026-10-14', 'frankfurter'),
  ('SGD', 0.779666, '2026-10-14', 'frankfurter'),
  ('THB', 0.029784, '2026-10-14', 'frankfurter'),
  ('VND', 0.000039, '2026-10-14', 'open_er_api');

-- migrate:down

DROP INDEX IF EXISTS jobs_experience_months_min;
ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_experience_months_has_min;
ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_experience_months_order;
ALTER TABLE jobs DROP COLUMN IF EXISTS experience_max_months;
ALTER TABLE jobs DROP COLUMN IF EXISTS experience_min_months;
DROP VIEW IF EXISTS job_base_pay;
DROP TABLE IF EXISTS job_compensation;
DROP TABLE IF EXISTS fx_rates;
DROP DOMAIN IF EXISTS months;
DROP DOMAIN IF EXISTS money_amount;
DROP DOMAIN IF EXISTS currency_code;
