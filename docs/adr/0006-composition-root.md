---
title: "ADR-0006: Ports, adapters, and one composition root"
date: 2026-10-12
status: accepted
related:
  - "PLAN.md §7 Source adapters"
  - "PLAN.md §13.8 Job fit"
  - "ADR-0004 Pluggable fit interface"
---

# ADR-0006: Ports, adapters, and one composition root

## Context

Fit, resume, facts, and scrape each grew a name registry. Adding an adapter meant a class, a registry line, and an environment variable (`FIT_MODEL`, `RESUME_AGENT`). [ADR-0004](0004-pluggable-fit-interface.md) described that for fit. A fork of this repo should change one place, not hunt for a lookup table.

## Decision

The core owns five ports: `JobSource`, `DetailParser`, `FitScorer`, `ResumeWriter`, and `Store`. An adapter is one class that implements a port.

`api/jobhunt/composition.py` is the only file that picks adapters. `COMPOSITION` is a frozen dataclass. Swapping an adapter is a new class plus one line in that file. Constructors stay cheap. Models and clients load on first use.

Pipelines take a `Composition`. They do not look up a name. The registries are gone. `FIT_MODEL` and `RESUME_AGENT` are gone.

An adapter with `sends_data_offsite = True` refuses to run unless `JOBHUNT_ALLOW_OFFSITE=1`. The check runs at use, not at import, because the default writer sends text to Claude.

Each `JobSource` owns a `SourceSpec` (`kind`, `min_interval`, `close_after`), `payload_facts`, `augment_text`, and `needs_detail_fetch`. The scrape pipeline upserts those columns into `sources` and does not change `enabled`. A new source needs no migration.

Stored `model_id` values do not change: `qwen3-embedding-0.6b/v1`, `claude-sdk/v1`, `fake/v1`.

## Consequences

- A custom parser or scorer is visible in one file. mypy rejects a class that does not fit the port.
- [ADR-0004](0004-pluggable-fit-interface.md) still describes the matrix scorer. The registry it named is replaced by this file.
- Two people editing `composition.py` can conflict. The file is short on purpose.
