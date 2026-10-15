"""The fit worker. Loads the model once and polls for work every minute.

Work, in order: due schedules, queued manual runs, then a bank scrape run
when a target job is unscored or changed and no scrape run is already queued.
One run at a time, and a restart resumes a run that was interrupted.
"""

import hashlib
from datetime import UTC, datetime
from typing import Any

from psycopg import Connection

from jobhunt.core.db import advisory_lock, pool, tx
from jobhunt.fit import repo as fit_repo
from jobhunt.fit.base import FitRateLimited, FitScorer
from jobhunt.fit.runner import _pending, score_batch
from jobhunt.fit.schedule import next_runs
from jobhunt.fit.sources import SourceError, resolve

_BATCH = 64


class StopRequested(Exception):
    """Raised between batches when the process was asked to shut down."""


def idempotency_key(mode: str, source_hash: str, slot: str, schedule_id: int | None) -> str:
    owner = "manual" if schedule_id is None else str(schedule_id)
    raw = f"{owner}|{mode}|{source_hash}|{slot}"
    return hashlib.sha256(raw.encode()).hexdigest()


def queue_run(
    conn: Connection[Any],
    *,
    mode: str,
    trigger: str,
    model_id: str,
    source_hash: str,
    slot: str,
    schedule_id: int | None = None,
) -> tuple[int, bool]:
    return fit_repo.enqueue_run(
        conn,
        {
            "schedule_id": schedule_id,
            "mode": mode,
            "trigger": trigger,
            "model_id": model_id,
            "idempotency_key": idempotency_key(mode, source_hash, slot, schedule_id),
        },
    )


def execute_run(
    model: FitScorer,
    run_id: int,
    *,
    limit: int | None = None,
    batch_size: int = _BATCH,
    should_stop: Any | None = None,
) -> None:
    """Score one claimed run, committing after every batch so a crash keeps it.

    Uses its own connection because it commits between batches, which a `tx()`
    block cannot do.
    """
    conn = pool().getconn()
    try:
        _execute(conn, model, run_id, limit, batch_size, should_stop or _stopping_flag)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool().putconn(conn)


def _execute(
    conn: Connection[Any],
    model: FitScorer,
    run_id: int,
    limit: int | None,
    batch_size: int,
    should_stop: Any,
) -> None:
    run = fit_repo.get_run(conn, run_id)
    if run is None:
        return
    try:
        source_hash, docs, _resume_id = resolve(conn, run["mode"], model)
    except SourceError as exc:
        _fail(conn, run_id, str(exc))
        return

    pending, skipped = _pending(conn, model.model_id, source_hash, limit)
    total = len(pending) + skipped
    scored = 0
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        if should_stop():
            fit_repo.requeue_run(conn, run_id)
            return
        try:
            score_batch(conn, model, docs, source_hash, batch)
        except FitRateLimited as exc:
            fit_repo.finish_fit_run(
                conn,
                run_id,
                status="partial",
                scored=scored,
                skipped=skipped,
                error=str(exc)[:500],
            )
            event_id = fit_repo.add_run_event(
                conn, run_id, "status", {"status": "partial", "error": str(exc)[:500]}
            )
            fit_repo.notify_run(conn, run_id, event_id)
            return
        scored += len(batch)
        event_id = fit_repo.add_run_event(
            conn,
            run_id,
            "progress",
            {"done": scored + skipped, "total": total, "pct": _percent(scored + skipped, total)},
        )
        fit_repo.notify_run(conn, run_id, event_id)
        conn.commit()
    fit_repo.mark_source_scored(conn, source_hash)
    # Count every job scored for this run, including batches a crashed attempt
    # committed before it was requeued.
    scored_total = conn.execute(
        "SELECT count(*) FROM job_fits WHERE model_id = %s AND source_hash = %s",
        (model.model_id, source_hash),
    ).fetchone()
    fit_repo.finish_fit_run(
        conn,
        run_id,
        status="ok",
        scored=int(scored_total[0]) if scored_total else scored,
        skipped=skipped,
        error=None,
    )
    event_id = fit_repo.add_run_event(conn, run_id, "status", {"status": "ok"})
    fit_repo.notify_run(conn, run_id, event_id)


def poll_once(model: FitScorer, *, now: datetime | None = None) -> None:
    """Queue whatever is due, then run the oldest queued run."""
    moment = now or datetime.now(UTC)
    with tx() as conn:
        fit_repo.heartbeat(conn, model.model_id)
        _queue_due(conn, model, moment)
        _queue_scrapes(conn, model, moment)
    with advisory_lock("jobhunt.fit") as acquired:
        if not acquired:
            return
        claimed_id = _claim()
        if claimed_id is not None:
            execute_run(model, claimed_id)


class _StopFlag:
    """Set by SIGTERM. Checked between batches, never mid-batch."""

    def __init__(self) -> None:
        self.requested = False

    def __call__(self) -> bool:
        return self.requested


_stopping_flag = _StopFlag()


def request_stop() -> None:
    """Finish the current batch, put the run back on the queue, and exit."""
    _stopping_flag.requested = True


def serve(model: FitScorer, *, interval: int = 60) -> None:
    """Poll until stopped. The model stays loaded for the life of the process."""
    import signal
    import time

    signal.signal(signal.SIGTERM, lambda *_args: request_stop())
    while not _stopping_flag():
        poll_once(model)
        time.sleep(interval)


def _claim() -> int | None:
    """Claim on a connection that commits, so the row stays claimed."""
    conn = pool().getconn()
    try:
        claimed = fit_repo.claim_run(conn)
        conn.commit()
        return None if claimed is None else int(claimed["id"])
    except Exception:
        conn.rollback()
        raise
    finally:
        pool().putconn(conn)


def _queue_due(conn: Connection[Any], model: FitScorer, now: datetime) -> None:
    for schedule in fit_repo.due_schedules(conn, now):
        try:
            source_hash, _docs, _resume_id = resolve(conn, schedule["mode"], model)
        except SourceError:
            continue
        slot = now.strftime("%Y-%m-%dT%H:%M")
        queue_run(
            conn,
            mode=schedule["mode"],
            trigger="schedule",
            model_id=model.model_id,
            source_hash=source_hash,
            slot=slot,
            schedule_id=int(schedule["id"]),
        )
        upcoming = next_runs(schedule["cron"], schedule["timezone"], 1, now=now)
        fit_repo.update_schedule(
            conn,
            int(schedule["id"]),
            {"last_run_at": now, "next_run_at": upcoming[0]},
        )


def _queue_scrapes(conn: Connection[Any], model: FitScorer, now: datetime) -> None:
    """Queue a scrape run when open jobs are unscored or changed and none is queued."""
    slot = now.strftime("%Y-%m-%dT%H:%M")
    for mode in ("bank",):
        try:
            source_hash, _docs, _resume_id = resolve(conn, mode, model)
        except SourceError:
            continue
        if not fit_repo.has_unscored_jobs(conn, model.model_id, source_hash):
            continue
        if fit_repo.has_queued_scrape_run(conn, mode, model.model_id):
            continue
        queue_run(
            conn,
            mode=mode,
            trigger="scrape",
            model_id=model.model_id,
            source_hash=source_hash,
            slot=slot,
        )


def _fail(conn: Connection[Any], run_id: int, message: str) -> None:
    fit_repo.finish_fit_run(conn, run_id, status="failed", scored=0, skipped=0, error=message)
    event_id = fit_repo.add_run_event(
        conn, run_id, "status", {"status": "failed", "error": message}
    )
    fit_repo.notify_run(conn, run_id, event_id)


def _percent(done: int, total: int) -> int:
    if total == 0:
        return 100
    return round(100 * done / total)
