---
title: "ADR-0003: Split into api/ and app/ with feature slices"
date: 2026-10-10
status: accepted
related:
  - "PLAN.md §4 Repository layout"
  - "ADR-0001 Single-tenant Postgres-backed task pipeline"
  - "ADR-0002 Brag docs replace the brag bank"
---

# ADR-0003: Split into api/ and app/ with feature slices

## Context

The repo mixed two stacks at the root. Python lived in `jobhunt/` (with `web/` routers and a `db/` package that held fit SQL), `tests/`, `db/migrations/`, and `config/`. Next.js lived in `web/`. Shared concepts such as jobs, brag docs, profile, and fit were spread across files named by layer (`routes.py`, `brag_api.py`, `fit_api.py`, `lib/api.ts`, `lib/types.ts`), so one feature touched five or six files in different folders.

## Decision

- Two self-contained subprojects. `api/` holds everything Python: package, migrations, seed config, tests, `pyproject.toml`, `uv.lock`, and its `Dockerfile`. `app/` holds everything Next.js: `src/`, config, `package.json`, its `Dockerfile`, and `AGENTS.md`. The root keeps `docker-compose.yml`, `Makefile`, `README.md`, `PLAN.md`, `.env.tpl`, and `docs/adr/`.
- Feature slices on both sides, with the same six names: `core` (shared plumbing), `scrape`, `jobs`, `brag`, `profile`, `fit`. On the frontend the slice lives in `src/features/<slice>/` (plus `shell` for the header and theme). Each slice owns its `api.ts` (server-only fetchers), `types.ts`, `actions.ts`, and `components/`.
- `jobhunt/core/paths.py` resolves `api/` paths (`config_path`, `migrations_dir`) from the module location, so the CLI works from any working directory.
- The HTTP contract does not change. The OpenAPI document from `create_app()` is identical before and after the move. Route modules are merged into their slices (`jobs/router.py`, `brag/router.py`, `profile/router.py`, `fit/router.py`, `scrape/router.py`).
- Thin routes. `src/app/**/page.tsx` only sets metadata and composes feature components; data fetching and UI move into the feature.

## Consequences

- A change to one feature stays inside one folder on each side. Reviewers can read a slice top to bottom.
- Make targets change directory: `check` and `api`/`jh` run in `api/`, `check-app` and `app` run in `app/`.
- Docker build contexts are `./api` (API and fit worker) and `./app` (UI). Each Dockerfile only copies its own project.
- The Next.js `AGENTS.md` now lives in `app/`. Tools that read it from the repo root will not find it.
- Shared code must stay small. Anything used by two slices on the backend goes to `core/`; on the frontend it goes to `components/` or `lib/`.
- Historical design text in `PLAN.md` (for example the planned `match/` module) is kept as spec history. The layout section (§4) reflects the current tree.
