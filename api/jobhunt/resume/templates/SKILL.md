---
name: tailor-resume-server
description: Tailor a one-page PDF resume from the shortlist and filler files in the working directory. Use when asked to generate or rewrite a resume for a job. Do not ask questions. Do not read or write outside the working directory except the kit scripts.
---

# Tailor a resume, unattended

Write one truthful one-page resume for the job in `JD.md`. Do not ask questions. Do not browse the network. Do not read Slack, GitHub, or a vault. Everything you may use is in this directory.

## Read first

Read only these four files, once:

1. `JD.md` — the job description. Map one bullet to each responsibility, in the job's words.
2. `shortlist.json` — brag docs that must all appear. Each item has `id`, `text`, and `aspect` (the requirement it covers).
3. `filler.json` — extra brag docs, best first. Use them only after every shortlist doc is on the page. Never drop a shortlist doc to make room.
4. `profile.md` — background for the summary line, not a source of new numbers.

Do not open the kit markdown. The prompt names `KIT` and `WORKDIR`.

## Rules

- Every bullet has a `src` array of brag doc ids. Every shortlist `id` appears in some `src`, including `profile` when the shortlist has it. Put `profile` on the first bullet and use one fact from `profile.md` there. Numbers match that doc. Estimates stay estimates.
- The bullet that cites a shortlist id must keep that item's `aspect` wording and the numbers from its `text`. Do not swap in synonyms.
- Lead with the biggest real number. Bold one metric per bullet with `**like this**`, never a technology name.
- Generic requirements (REST, OOP, Jira) go in the skills line, not bullets.
- Summary is two lines: years and stack, strongest proof, and why this team.
- Fill the page. Do not shrink type. If it overflows, cut the weakest filler line. If it is short, add the next filler doc.
- Paper is `a4` unless the job is in the US, then `letter`.
- Do not invent employers, titles, dates, or metrics.

## Write

`resume.json` uses these keys, or the renderer crashes:

- `name` is a top-level string. It is not inside `contact`.
- `contact` has `location`, `email`, and `links` (`[{label, url}]`).
- `summary` is a string.
- `skills` is a list of `{label, items}`. `items` is a list of strings, not a string.
- `experience` is a list of `{company, roles}`. Each role has `title`, `start`, `end`, and `bullets`. Each bullet is `{text, src}`.
- `meta` is `{page_limit: 1, paper: "a4"}`, or `"letter"` when the job is in the US.

Then run, with the real paths from the prompt:

```bash
python KIT/render_resume.py WORKDIR/resume.json WORKDIR/resume.pdf
python KIT/lint_resume.py WORKDIR/resume.json --pdf WORKDIR/resume.pdf > WORKDIR/lint.txt
```

If lint prints a FAIL, fix `resume.json` once and run both commands once more. Then stop, even if a WARN remains. Do not re-read the inputs.

If `feedback.md` exists, add the missing words to the bullets that are already there. Do not delete a number or a shortlist bullet.
