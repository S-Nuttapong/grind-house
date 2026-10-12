---
title: "ADR-0007: Claude parser and fit scorer, contract checks, and evals"
date: 2026-10-12
status: accepted
related:
  - "ADR-0006 Ports, adapters, and one composition root"
  - "PLAN.md §9 Ingest"
  - "PLAN.md §13.8 Job fit"
---

# ADR-0007: Claude parser and fit scorer, contract checks, and evals

## Context

Board payloads leave role, level, location, and pay empty often enough that a rule parser cannot fill them. The fit starter is a local embedding model. Both need an adapter that calls Claude Haiku 5.5, and a check that runs before anything is stored, so a bad reply cannot write a salary or a doc id that was not in the input.

## Decision

`core/claude.py` exposes `structured_call`. It uses `messages.parse`, caches the system block, retries a truncated or invalid reply once, and logs tokens and cost. It does not log the prompt. A refusal is not retried. The model is `claude-haiku-5-5`. The SDK is the optional `claude` extra, `anthropic==1.13.0`.

`ClaudeParser` returns role, level, workplace, job type, location, pay, and posted date. Role is a slug from `config/roles.yaml` or unknown. Level comes from the title or explicit seniority wording, never from years alone. When in doubt the model returns unknown, which is stored as empty. Board facts already on the input are kept. `parser_id` is `claude-haiku-5-5/v1`.

`ClaudeFitScorer` returns a score and matches of `(aspect_index, brag_doc_id, similarity)`. Coverage, gaps, and the selected docs are computed in code from that list. `model_id` is `claude-haiku-5-5/v1`. A batch that cannot run falls back to one job at a time.

`facts/contract.py` and `fit/contract.py` run on every adapter's output. A failing field is dropped and the rule id is logged. Evidence must be a verbatim substring of the title or description, except facts whose `parser_id` starts with `api:`. Pay must be a positive amount inside a wide per-interval band, with an ISO currency. Posted dates must be within the last 365 days and not in the future. Role and level must be known values. Fit matches must cite a doc id from the input.

A parser exception stores an empty `JobDetail` with `facts_status = 'failed'`.

`eval_parser` and `eval_fit` take the adapter object. Parser gates are hallucination at most 2%, precision at least 0.95, and schema-valid at least 99.5%. Fit gates are Spearman at least as high as the baseline, and retest standard deviation at most 5 points. The gold file and the replay cache are gitignored.

`jobhunt facts backfill` runs the composed parser on stored payloads, then the contract, then `save_facts` and `merge_facts`. It fills empty columns only. Role, location, and level come first. Pay is best effort. It refuses unless `COMPOSITION.parser` is `ClaudeParser` and `JOBHUNT_ALLOW_OFFSITE=1`. It does not run until the parser gates pass for role, level, and location on a gold file a person has checked. The default in `composition.py` stays `DefaultParser` until then.

Claude token rows are not written to `agent_usage`.

## Consequences

- Swapping in Claude is one line in `composition.py`. The contract does not depend on which adapter produced the facts.
- A backfill of the open jobs is a few dollars at the short-prompt Haiku 5.5 rates, after the gold file passes. Until it passes, the command is implemented and not the default.
- Prompt text stays out of logs. The API key stays in gitignored `.env`.
