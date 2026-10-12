---
title: "ADR-0005: Resume agent with a fit gate and a cost log"
date: 2026-10-10
status: accepted
related:
  - "PLAN.md §16 Tailor handoff"
  - "ADR-0001 Single-tenant Postgres-backed task pipeline"
  - "ADR-0004 Pluggable fit interface"
---

# ADR-0005: Resume agent with a fit gate and a cost log

## Context

A job card shows the description and the brag docs the fit model selected. Turning those into a one-page resume was a manual handoff to the `tailor-resume` skill in Claude Desktop. That skill pauses to ask questions, reads the Obsidian vault, and runs render and lint scripts on the laptop. A button in the app cannot do that, and a remote host will not have the vault mounted.

The resume still has to be truthful, one page, and at least as good a match as the shortlist it was built from. Generating it calls Claude, so each run has a dollar cost that should be recorded without showing it on the job card.

## Decision

We will generate resumes through a `ResumeAgent` interface. `generate(request, workdir)` takes the job description, the fit shortlist, filler brag docs, and the profile, and returns `resume.json`, a PDF, the lint report, and token usage.

The first adapter is the Claude Agent SDK (`claude-agent-sdk`) on `claude-haiku-5-5`, overridable with `RESUME_MODEL`. The SDK runs the agent loop and the Read, Write, Bash, and Skill tools. We do not flatten the skill into a system prompt. A server copy of the skill, `tailor-resume-server`, is synced into a gitignored kit directory and loaded from the run's working directory. It keeps the writing rules and drops the vault paths, the questions, and the desktop research. The agent may only run `render_resume.py` and `lint_resume.py` from that kit, and may only write inside the working directory.

The worker reads Postgres, the kit directory, and environment variables. It writes a temp directory and Postgres. It never reads the vault at run time, so local and remote differ only in configuration.

Work is a row in `resume_runs`. The API inserts it and sends `NOTIFY resume_runs`. The worker listens, with a 30 second fallback, and claims with `FOR UPDATE SKIP LOCKED` and a 15 minute lease. One run per process.

Every shortlist doc must appear on the resume. Other brag docs fill the page, ordered by an `impact` rating (1–5, set on the brag doc) and then by similarity to this job. Unrated docs sort last. Filler never replaces a shortlist doc.

After render, the same fit model scores the bullets whose source is a shortlist doc. The resume must score at least the stored job fit and must still cover every requirement the shortlist covered. Filler bullets are reported and do not fail the gate. Up to two rewrites get the lost requirements as feedback. A rewrite that scores lower is discarded, and the higher draft is kept. After that, `RESUME_GATE=warn` (the default) stores the PDF as `below_baseline`. `fail` stores no PDF. A model mismatch skips the gate and logs that. A one-page bullet cannot carry the embedding of a multi-thousand-character source doc, so a long shortlist can land a few points under its baseline even when every doc is cited. That is `below_baseline`, not a failed render.

Each attempt writes one `agent_usage` row: model, token counts, turns, duration, and cost in USD. The row has no prompt and no resume text. `GET /api/admin/usage` and `/admin/usage` show it. They are not linked from the header. A run stops starting new attempts once its cost exceeds `RESUME_MAX_COST_USD` (default 5).

`sends_data_offsite` is true. The agent refuses to load unless `FIT_ALLOW_OFFSITE=1`. `ANTHROPIC_API_KEY` comes from the environment.

Acceptance, checked by `jobhunt resume check` and the Playwright UAT:

1. The run status is `ok`.
2. The PDF is one page and lint reports no failure.
3. The lint report has no FAIL.
4. Every shortlist id is cited, and every citation exists.
5. The resume score is at least the baseline, and no covered requirement was lost.
6. Usage was logged with a cost above 0 and at most the cap.
7. The run finishes in under 5 minutes.
8. The job card shows the download, both scores, and the filler docs, with no browser console errors.

## Consequences

- Adding another generator is one class and one registry line. The queue, the gate, and the job card stay.
- Brag docs and job descriptions are sent to Anthropic when a resume is generated. The opt-in is the same switch as an offsite fit model.
- The admin page and the admin API have no authentication while the app binds to loopback. Both need authentication before the API is reachable from anywhere else.
- Remote hosting, container hardening, and egress limits are not built here. The worker's inputs and outputs are already limited to Postgres, the kit, and a temp directory, which is what a later hardened container needs.
- Haiku 5.5 is fast and cheap, and a weaker writer than a larger model. `RESUME_MODEL` changes that without a code change. The $5 cap is a backstop, not the expected cost.
- Impact is optional. Until docs are rated, filler order is similarity alone.

## Alternatives considered

- Paste the skill into a system prompt. Rejected: the prompt would drift from the skill, and the model could not run the kit scripts.
- Call the Messages API and implement the tool loop. Rejected: the Agent SDK already runs that loop and loads skills.
- Run the Claude CLI as a subprocess. Rejected: the SDK bundles that CLI and returns typed usage.
- Fail the run whenever the resume scores below the shortlist. Rejected as the default: embedding scores move by a point or two, and one page can force a cut. The PDF is still delivered, marked below baseline, and `RESUME_GATE=fail` is available.
