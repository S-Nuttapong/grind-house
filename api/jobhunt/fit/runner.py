"""Score the jobs that changed since the last run for one profile source."""

from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from jobhunt.core.log import get_logger
from jobhunt.fit import repo as fit_repo
from jobhunt.fit.aspects import split_aspects
from jobhunt.fit.base import BragDoc, FitResult, FitScorer, FitUnavailable
from jobhunt.fit.contract import check_fit
from jobhunt.fit.keywords import compare
from jobhunt.fit.sources import job_hash, joined_text, resolve

log = get_logger("fit")

_BATCH = 64


def run_fit(
    conn: Connection[Any], model: FitScorer, mode: str, *, limit: int | None = None
) -> dict[str, int]:
    """Score open jobs whose text changed. Returns {scored, skipped}."""
    source_hash, docs, _resume_id = resolve(conn, mode, model)
    pending, skipped = _pending(conn, model.model_id, source_hash, limit)
    scored = 0
    for start in range(0, len(pending), _BATCH):
        batch = pending[start : start + _BATCH]
        score_batch(conn, model, docs, source_hash, batch)
        scored += len(batch)
    fit_repo.mark_source_scored(conn, source_hash)
    return {"scored": scored, "skipped": skipped}


def score_batch(
    conn: Connection[Any],
    model: FitScorer,
    docs: list[BragDoc],
    source_hash: str,
    batch: list[dict[str, Any]],
) -> None:
    """Score one batch and store the fit row plus the selected docs."""
    descriptions = [row["description_md"] or row["title"] for row in batch]
    results = _score_all(model, docs, descriptions)
    profile_text = joined_text(docs)
    doc_ids = {doc.id for doc in docs}
    for row, result in zip(batch, results, strict=True):
        if result is None:
            continue
        description = row["description_md"] or ""
        result = check_fit(
            result,
            doc_ids=doc_ids,
            aspects=split_aspects(description or row["title"]),
        )
        matched, missing = compare(profile_text, f"{row['title']}\n{description}")
        fit_repo.upsert_job_fit(
            conn,
            {
                "job_id": row["id"],
                "model_id": model.model_id,
                "source_hash": source_hash,
                "job_hash": job_hash(row["title"], description),
                "score": result.score,
                "raw": result.raw,
                "coverage": result.coverage,
                "gaps": result.gaps,
                "matched_terms": matched,
                "missing_terms": missing,
            },
        )
        fit_repo.replace_matches(
            conn,
            job_id=int(row["id"]),
            model_id=model.model_id,
            source_hash=source_hash,
            matches=[
                {
                    "doc_ref": match.brag_doc_id,
                    "aspect": match.aspect,
                    "similarity": match.similarity,
                }
                for match in result.top_docs
            ],
        )


def _score_all(
    model: FitScorer, docs: list[BragDoc], descriptions: list[str]
) -> list[FitResult | None]:
    try:
        return list(model.fit_many(docs, descriptions))
    except FitUnavailable:
        log.warning("fit batch unavailable; scoring one job at a time")
        found: list[FitResult | None] = []
        for description in descriptions:
            try:
                found.append(model.fit(docs, description))
            except FitUnavailable:
                log.warning("fit unavailable; leaving the job for the next run")
                found.append(None)
        return found


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
