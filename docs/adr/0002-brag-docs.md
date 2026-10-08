---
title: "ADR-0002: Brag docs replace the brag bank"
date: 2026-10-08
status: accepted
related:
  - "PLAN.md §2 Guardrails"
  - "PLAN.md §11 Profile from the brag docs"
  - "PLAN.md §14 Web UI"
---

# ADR-0002: Brag docs replace the brag bank

## Context

The brag bank stored one row per accomplishment (`bank_entries`) with tags as a text array, metrics as free-form JSON, and a period written as a range (`2025-08 – 2025-09`). Finding "every win that saved engineering hours" meant scanning JSON, and the form asked for fields the user does not use: a 1–5 strength, a draft/verified status, and a confidential flag.

The vault at `VAULT_BANK_PATH` is the source of those entries. PLAN.md §2 says the app never writes to it.

## Decision

Replace `bank_entries` with `brag_docs`, `tags`, `metric_keys`, `brag_doc_tags`, `brag_doc_metrics`, and `brag_doc_attachments`.

- A brag doc has a `date`. Postgres stores `quarter` as a generated column, so the user never types it.
- Tags and metric keys are their own tables, unique on a case-insensitive name. Creating "React" twice returns the same row.
- A metric is a key plus a text value (`Latency Reduction: 200ms`).
- Drop `my_role`, `period`, `scope`, `strength`, `status`, and `confidential`. Keep `role` and `company`. The description is the old body, unchanged.
- Because nothing is marked confidential, fit scoring no longer filters brag docs out of an offsite model. The fit mode stays `bank`.

The existing rows are copied in `20261009000004_brag_docs.sql`. The date is the last day of the month the period ends in, or `updated_at` when the period does not parse. A metric's `kind` becomes the key (`page-experience` becomes "Page Experience"; a metric with no kind uses "General") and its `text` becomes the value.

`jobhunt brag-docs migrate-vault --write` rewrites the vault frontmatter to the new shape once. It copies `Entries/` to `~/.jobhunt/vault-backups/<timestamp>/` first, changes only the frontmatter, and skips files already migrated. Without `--write` it prints what it would do. `jobhunt profile import` stays read-only and reads the new shape.

## Consequences

- The feed groups by quarter, and a metric-key filter returns only the docs that carry that key.
- Editing a brag doc changes the bank source hash, so the next fit run rescores. Scores already stored stay until then.
- The one-time vault rewrite is the only write this app makes to the vault. A second run does nothing.
- Old frontmatter fields are not recoverable from the database after the migration. The backup outside the vault is the copy.
