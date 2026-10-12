---
title: "ADR-0004: Pluggable fit interface with a local matrix starter"
date: 2026-10-10
status: accepted
related:
  - "PLAN.md §13.8 Job fit"
  - "ADR-0001 Single-tenant Postgres-backed task pipeline"
  - "ADR-0002 Brag docs replace the brag bank"
---

# ADR-0004: Pluggable fit interface with a local matrix starter

## Context

Fit scoring merged every brag doc into one profile string, chunked that string, and reduced a job-chunk by profile-chunk cosine matrix. The stored result was one number. A resume for a job needs the opposite: which brag docs cover which parts of the job description. The reduction also claimed "one chunk per entry" and did not do that, so a chunk could straddle two docs.

The starter has to run locally, stay free, and not call a generative model. Later strategies, including an LLM, must plug in without changing the worker or the board.

## Decision

Every strategy implements `JobFitModel.fit(docs, job_description) -> FitResult`.

- Input is the brag docs (id and text) and one job description.
- Output is a 0–100 score, the uncalibrated aggregate, a coverage value, the selected docs (each with the job aspect it covers and a similarity from 0 to 1), and the aspects nothing covers well enough.
- `fit_many` scores a batch. Embedding models override it to encode the docs once.
- `sends_data_offsite` stays on the model. `FIT_MODEL` factories that set it to true refuse to load unless `FIT_ALLOW_OFFSITE=1`.

The starter, `FIT_MODEL=qwen3`, is `MatrixFitModel` with `Qwen/Qwen3-Embedding-0.6B` ([Zhang et al., arXiv:2506.05176](https://arxiv.org/abs/2506.05176), Apache 2.0). It is an embedding model, not a generator. Each brag doc is one vector. The job description is split into requirement bullets, and sections titled benefits, perks, about us, EEO, or salary are dropped. Aspects are encoded with the instruction "Given a job requirement, retrieve resume achievements that demonstrate it."

The doc × aspect cosine matrix is reduced by greedy facility-location coverage ([Lin and Bilmes, ACL 2011](https://aclanthology.org/P11-1052/)): each step adds the doc that most increases the sum over aspects of the best similarity so far, up to 10 docs or until the gain falls below 0.01. The score is the mean, over the selected docs, of each doc's best aspect similarity, then calibrated from that model's cosine range to 0–100. This is the same row-max-then-mean reduction as BERTScore ([Zhang et al., ICLR 2020](https://arxiv.org/abs/1904.09675)), applied to the docs that would go on a resume, so unrelated docs in a large bank do not lower the score.

`bge` is the same matrix model with `BAAI/bge-base-en-v1.5` and its query prefix, so the two encoders can be compared. `fake` stays for tests and uses term overlap instead of embeddings. `jobhunt fit eval --labels` reports Spearman correlation and hit@10 against a private label file that is not committed.

`job_fits` gains `coverage` and `gaps`. `job_fit_matches` stores the selected docs. The board still shows one score per job. The detail pane lists the selected docs.

## Consequences

- Adding an LLM or another encoder is one class and one registry line. The worker, the API, and the detail pane do not change.
- A model switch writes a new `model_id`. The board shows the latest computed row, so old BGE scores remain until the new model scores that job.
- Qwen3's cosine range is not the same as BGE's. Each model has its own calibration floor and span. `jobhunt fit calibrate` prints a floor and span from the 5th and 95th percentile of stored raw scores; it does not rewrite the constants.
- Offsite models stay opt-in because brag docs can contain employer-confidential numbers.
- The resume PDF step is not part of this decision. It will read `top_brags` and the job description later.
