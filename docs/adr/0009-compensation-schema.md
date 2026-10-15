---
title: "ADR-0009: Compensation table and experience in months"
date: 2026-10-15
status: accepted
related:
  - "ADR-0007 Claude parser and fit scorer"
---

# ADR-0009: Compensation table and experience in months

## Context

Pay was five nullable columns on `jobs`. The currency was `char(3)`, amounts were whole numbers, and the USD value was stored, so it went stale when rates changed. A salary with only a maximum was written into a column named min. Experience was whole years, so "6 months" could not be stored.

## Decision

Follow Google Cloud Talent Solution's compensation model and the PostgreSQL guidance against `money` and `char(n)`.

`job_compensation` has one row per pay component, at most one `base` row per job. Amounts use `numeric`. Annual amounts are generated columns (`amount × units_per_year`). USD is not stored: the `job_base_pay` view multiplies by `fx_rates` at read time.

`fx_rates` is filled from Frankfurter. open.er-api.com supplies only currencies Frankfurter does not quote (VND today). The tick refreshes rates when the last fetch is older than a day. A failed fetch keeps the previous rows.

Experience is `experience_min_months` and `experience_max_months` on `jobs`. The older year columns stay until readers move over.

Range types are deferred. The filters compare one bound, and a few thousand rows do not need an index on the derived USD value.

## Consequences

- A currency with no rate keeps its local amount and has no USD value, so a USD filter skips it.
- open.er-api's free terms require an attribution link on the board. That lands with the salary filter.
- Dropping `jobs.salary_*` is a later migration, after reads and writes use `job_compensation`.
