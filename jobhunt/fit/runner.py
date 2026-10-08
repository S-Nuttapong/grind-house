"""Score the jobs that changed since the last run for one profile source."""

from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from jobhunt.db import fit_repo
from jobhunt.fit.base import JobFitModel
from jobhunt.fit.keywords import compare
from jobhunt.fit.sources import job_hash, resolve

_BATCH = 64


def run_fit(
    conn: Connection[Any], model: JobFitModel, mode: str, *, limit: int | None = None
) -> dict[str, int]:
    """Score open jobs whose text changed. Returns {scored, skipped}."""
    source_hash, profile_text, _resume_id = resolve(conn, mode, model)
    pending, skipped = _pending(conn, model.model_id, source_hash, limit)
    scored = 0
    for start in range(0, len(pending), _BATCH):
        batch = pending[start : start + _BATCH]
        descriptions = [row["description_md"] or row["title"] for row in batch]
        scores = model.score_many(profile_text, descriptions)
        for row, score in zip(batch, scores, strict=True):
            description = row["description_md"] or ""
            matched, missing = compare(profile_text, f"{row['title']}\n{description}")
            fit_repo.upsert_job_fit(
                conn,
                {
                    "job_id": row["id"],
                    "model_id": model.model_id,
                    "source_hash": source_hash,
                    "job_hash": job_hash(row["title"], description),
                    "score": score,
                    "raw": score,
                    "matched_terms": matched,
                    "missing_terms": missing,
                },
            )
            scored += 1
    fit_repo.mark_source_scored(conn, source_hash)
    return {"scored": scored, "skipped": skipped}


def _pending(
    conn: Connection[Any], model_id: str, source_hash: str, limit: int | None
) -> tuple[list[dict[str, Any]], int]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, title, description_md FROM jobs
            WHERE closed_at IS NULL
            ORDER BY id
            """
        )
        rows = [dict(row) for row in cursor.fetchall()]
    stored = _stored_hashes(conn, model_id, source_hash)
    pending: list[dict[str, Any]] = []
    skipped = 0
    for row in rows:
        current = job_hash(row["title"], row["description_md"])
        if stored.get(row["id"]) == current:
            skipped += 1
        else:
            pending.append(row)
    if limit is not None:
        pending = pending[:limit]
    return pending, skipped


def _stored_hashes(conn: Connection[Any], model_id: str, source_hash: str) -> dict[int, str]:
    cursor = conn.execute(
        "SELECT job_id, job_hash FROM job_fits WHERE model_id = %s AND source_hash = %s",
        (model_id, source_hash),
    )
    return {int(row[0]): str(row[1]) for row in cursor.fetchall()}
