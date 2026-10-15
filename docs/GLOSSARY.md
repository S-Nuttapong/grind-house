# Glossary

One word per concept. New migrations and new code use these names. Rename an existing column only when a change is already editing that table.

## Things

| Say this | Not this | Meaning |
|---|---|---|
| job | posting, listing | One real role at one company. The `jobs` row. |
| posting | job, listing | One place that job was seen. The `postings` row, tied to a source. |
| brag doc | bank entry, bullet | One achievement, id `BB-###`. Fit mode `bank` scores these. |
| fit | match, band, rubric | How well a job fits the brag docs or the selected resume. Stored in `job_fits`. |
| tier | band | `strong` (≥ 80), `good` (≥ 60), `fair` (≥ 40), `low` (below 40). The API field is `fit_tier`. |
| application tracker | pipeline | The `/tracker` page of saved, applied, and not-interested jobs. "Pipeline" means only the scrape, fit, or resume code path. |
| company | employer | A row in `companies`. `name_norm` is the match key. |

## Runs

| Kind | Table | What it is |
|---|---|---|
| scrape | `runs` | One fetch of a source or a search market. |
| fit | `fit_runs` | One scoring pass over open jobs. |
| resume | `resume_runs` | One generated resume for one job. |

## Status values

Stored on `job_events.status`. The newest event that is not `removed` is the job's status.

| Stored | Shown as |
|---|---|
| `saved` | Saved |
| `applied` | Applied |
| `screening` | Screening |
| `interviewing` | Interviewing |
| `offer` | Offer |
| `skipped` | Not interested |
| `rejected` | Rejected |
| `rejected` with reason `no_response` | No response |
| `withdrawn` | Withdrawn |
| `removed` | (left the tracker; the board shows it as unsaved) |

## Timestamps

A timestamp column is a past-tense verb plus `_at`: `created_at`, `updated_at`, `started_at`, `finished_at`, `queued_at`, `scored_at`, `posted_at`, `closed_at`, `notified_at`, `labeled_at`, `matched_at`, `fetched_at`, `computed_at`, `heartbeat_at`.

`created_at` is for a row that is inserted and not a named event. An event uses the verb: a run starts at `started_at`, a label is applied at `labeled_at`. Do not add a bare `at` or `ran_at` on a new table.
