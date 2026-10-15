---
title: "ADR-0011: Job fit replaces the unused rubric tables"
date: 2026-10-15
status: accepted
related:
  - "PLAN.md §13.8 Job fit"
  - "ADR-0001 Single-tenant Postgres-backed task pipeline"
  - "ADR-0004 Pluggable fit interface"
---

# ADR-0011: Job fit replaces the unused rubric tables

## Context

PLAN.md §12 through §13.7 described a second scoring path: a filter DSL, hard filters, a keyword prefilter, an LLM rubric, and saved rules. The tables for that path (`profiles`, `requirements`, `prefilter`, `matches`, `match_criteria`, `rules`, `rule_hits`) were created in the first migration and never read or written. Fit scores live in `job_fits`, and the board shows `fit_tier` (strong, good, fair, low).

The API also carried a `band` field (`apply`, `maybe`, `skip`) that every response left null. `labels` is different: it stores a person's calibration choice, and code still writes it.

## Decision

Drop the seven unused tables. Scoring is `job_fits` and `fit_tier` only. Remove `band` from the job API. Keep `labels`.

Sections 12 through 13.7 of PLAN.md, and the tasks and MCP tools that only existed for that path, are deleted. §13.8 is the scoring spec.

## Consequences

- A database that already ran the first migration drops the empty tables in `20261015000022_drop_rubric.sql`. The down migration recreates them empty.
- `jobhunt match` and `jobhunt mcp` stay unimplemented stubs. They do not grow a second scorer.
- Gmail status updates are not planned. Application status stays a manual event.
