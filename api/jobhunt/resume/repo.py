"""SQL for resume runs, artifacts, and the internal cost log."""

from decimal import Decimal
from typing import Any

from psycopg import Connection
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

_LEASE = "15 minutes"


def enqueue(
    conn: Connection[Any],
    *,
    job_id: int,
    agent_id: str,
    model: str,
    fit_model_id: str,
    fit_source_hash: str,
) -> tuple[int, bool]:
    """Insert a queued run and wake the worker. Returns (id, created)."""
    existing = _active(conn, job_id)
    if existing is not None:
        return existing, False
    try:
        with conn.transaction():
            row = conn.execute(
                """
                INSERT INTO resume_runs (job_id, agent_id, model, fit_model_id, fit_source_hash)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (job_id, agent_id, model, fit_model_id, fit_source_hash),
            ).fetchone()
    except UniqueViolation:
        active = _active(conn, job_id)
        if active is None:
            raise
        return active, False
    if row is None:
        raise RuntimeError("enqueue returned no id")
    run_id = int(row[0])
    conn.execute("SELECT pg_notify('resume_runs', %s)", (str(run_id),))
    return run_id, True


def claim(conn: Connection[Any]) -> dict[str, Any] | None:
    """Claim the oldest queued run, or a running run whose lease expired."""
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute(
            f"""
            UPDATE resume_runs
            SET status = 'running',
                locked_until = now() + interval '{_LEASE}',
                started_at = coalesce(started_at, now())
            WHERE id = (
                SELECT id FROM resume_runs
                WHERE status = 'queued'
                   OR (status = 'running' AND locked_until < now())
                ORDER BY created_at, id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING *
            """
        )
        row = cursor.fetchone()
    return dict(row) if row else None


def set_fit_source(conn: Connection[Any], run_id: int, model_id: str, source_hash: str) -> None:
    """Point a run at the shortlist the worker just scored."""
    conn.execute(
        """
        UPDATE resume_runs SET fit_model_id = %s, fit_source_hash = %s WHERE id = %s
        """,
        (model_id, source_hash, run_id),
    )


def extend_lease(conn: Connection[Any], run_id: int) -> None:
    conn.execute(
        f"""
        UPDATE resume_runs SET locked_until = now() + interval '{_LEASE}'
        WHERE id = %s AND status = 'running'
        """,
        (run_id,),
    )


def requeue(conn: Connection[Any], run_id: int) -> None:
    conn.execute(
        """
        UPDATE resume_runs
        SET status = 'queued', locked_until = NULL, finished_at = NULL
        WHERE id = %s
        """,
        (run_id,),
    )


def add_event(conn: Connection[Any], run_id: int, kind: str, payload: dict[str, Any]) -> int:
    row = conn.execute(
        """
        INSERT INTO resume_run_events (run_id, kind, payload)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (run_id, kind, Jsonb(payload)),
    ).fetchone()
    if row is None:
        raise RuntimeError("add_event returned no id")
    event_id = int(row[0])
    conn.execute("SELECT pg_notify(%s, %s)", (f"resume_run_{run_id}", str(event_id)))
    return event_id


def record_usage(conn: Connection[Any], run_id: int, attempt: int, usage: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO agent_usage (
            run_kind, run_id, attempt, agent_id, model,
            input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
            num_turns, duration_ms, cost_usd, cost_source,
            purpose, job_id, success, error
        )
        VALUES (
            'resume', %(run_id)s, %(attempt)s, %(agent_id)s, %(model)s,
            %(input_tokens)s, %(output_tokens)s, %(cache_read_tokens)s, %(cache_write_tokens)s,
            %(num_turns)s, %(duration_ms)s, %(cost_usd)s, %(cost_source)s,
            'resume', NULL, true, NULL
        )
        """,
        {"run_id": run_id, "attempt": attempt, **usage},
    )


def cost_for_run(conn: Connection[Any], run_id: int) -> Decimal:
    row = conn.execute(
        """
        SELECT coalesce(sum(cost_usd), 0) FROM agent_usage
        WHERE run_kind = 'resume' AND run_id = %s
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        return Decimal(0)
    return Decimal(row[0])


def finish(
    conn: Connection[Any],
    run_id: int,
    *,
    status: str,
    baseline_score: float | None,
    baseline_coverage: float | None,
    resume_score: float | None,
    resume_coverage: float | None,
    lost_aspects: list[str],
    filler_ids: list[str],
    attempts: int,
    error: str | None,
) -> None:
    conn.execute(
        """
        UPDATE resume_runs SET
            status = %s, locked_until = NULL, attempts = %s,
            baseline_score = %s, baseline_coverage = %s,
            resume_score = %s, resume_coverage = %s,
            lost_aspects = %s, filler_ids = %s, error = %s, finished_at = now()
        WHERE id = %s
        """,
        (
            status,
            attempts,
            baseline_score,
            baseline_coverage,
            resume_score,
            resume_coverage,
            lost_aspects,
            filler_ids,
            error,
            run_id,
        ),
    )


def save_artifact(
    conn: Connection[Any], run_id: int, *, pdf: bytes, resume_json: dict[str, Any], lint_report: str
) -> None:
    conn.execute(
        """
        INSERT INTO resume_artifacts (run_id, pdf, resume_json, lint_report)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (run_id) DO UPDATE SET
            pdf = EXCLUDED.pdf, resume_json = EXCLUDED.resume_json,
            lint_report = EXCLUDED.lint_report
        """,
        (run_id, pdf, Jsonb(resume_json), lint_report),
    )


def latest_status(conn: Connection[Any], job_id: int) -> str | None:
    """Status of the newest run for a job, if one exists."""
    row = conn.execute(
        """
        SELECT status FROM resume_runs
        WHERE job_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (job_id,),
    ).fetchone()
    return None if row is None else str(row[0])


def queued_ahead(conn: Connection[Any], run_id: int) -> int | None:
    """How many active runs were created before this queued run. None when it is not queued."""
    row = conn.execute(
        """
        SELECT CASE WHEN run.status = 'queued' THEN (
            SELECT count(*) FROM resume_runs other
            WHERE other.status IN ('queued', 'running')
              AND (other.created_at, other.id) < (run.created_at, run.id)
        ) END
        FROM resume_runs run
        WHERE run.id = %s
        """,
        (run_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


def queue_snapshot(
    conn: Connection[Any], recent_limit: int = 20
) -> dict[str, list[dict[str, Any]]]:
    """Active runs in queue order, then the latest finished runs."""
    return {
        "active": _queue_rows(conn, ("queued", "running"), recent=False, limit=None),
        "recent": _queue_rows(
            conn, ("ok", "below_baseline", "failed"), recent=True, limit=recent_limit
        ),
    }


def _queue_rows(
    conn: Connection[Any], statuses: tuple[str, ...], *, recent: bool, limit: int | None
) -> list[dict[str, Any]]:
    order = "r.finished_at DESC NULLS LAST, r.id DESC" if recent else "r.created_at, r.id"
    ahead = (
        "NULL::int AS ahead"
        if recent
        else "(row_number() OVER (ORDER BY r.created_at, r.id) - 1)::int AS ahead"
    )
    limited = "" if limit is None else "LIMIT %s"
    values: list[Any] = [list(statuses)]
    if limit is not None:
        values.append(limit)
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute(
            f"""
            SELECT r.id, r.job_id, r.status, r.error,
                   r.baseline_score, r.resume_score,
                   r.created_at, r.started_at, r.finished_at,
                   j.title, c.name AS company,
                   {ahead}
            FROM resume_runs r
            JOIN jobs j ON j.id = r.job_id
            JOIN companies c ON c.id = j.company_id
            WHERE r.status = ANY(%s)
            ORDER BY {order}
            {limited}
            """,
            values,
        )
        return list(cursor.fetchall())


def get_run(conn: Connection[Any], run_id: int) -> dict[str, Any] | None:
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute("SELECT * FROM resume_runs WHERE id = %s", (run_id,))
        row = cursor.fetchone()
    return dict(row) if row else None


def list_for_job(conn: Connection[Any], job_id: int) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute(
            "SELECT * FROM resume_runs WHERE job_id = %s ORDER BY created_at DESC", (job_id,)
        )
        return list(cursor.fetchall())


def events_after(conn: Connection[Any], run_id: int, after_id: int) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute(
            """
            SELECT * FROM resume_run_events
            WHERE run_id = %s AND id > %s
            ORDER BY id
            """,
            (run_id, after_id),
        )
        return list(cursor.fetchall())


def artifact(conn: Connection[Any], run_id: int) -> dict[str, Any] | None:
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute(
            "SELECT run_id, pdf, resume_json, lint_report FROM resume_artifacts WHERE run_id = %s",
            (run_id,),
        )
        row = cursor.fetchone()
    return dict(row) if row else None


def usage_for_run(conn: Connection[Any], run_id: int) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute(
            """
            SELECT * FROM agent_usage
            WHERE run_kind = 'resume' AND run_id = %s
            ORDER BY attempt
            """,
            (run_id,),
        )
        return list(cursor.fetchall())


def usage_summary(conn: Connection[Any], *, days: int) -> dict[str, Any]:
    totals = conn.execute(
        """
        SELECT count(*), coalesce(sum(cost_usd), 0),
               coalesce(sum(input_tokens), 0), coalesce(sum(output_tokens), 0)
        FROM agent_usage
        WHERE created_at >= now() - make_interval(days => %s)
        """,
        (days,),
    ).fetchone()
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute(
            """
            SELECT created_at::date AS day, purpose, model,
                   count(*) AS runs, sum(cost_usd) AS cost_usd,
                   sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens
            FROM agent_usage
            WHERE created_at >= now() - make_interval(days => %s)
            GROUP BY 1, 2, 3
            ORDER BY 1 DESC, 2, 3
            """,
            (days,),
        )
        by_day = list(cursor.fetchall())
        cursor.execute(
            """
            SELECT u.id, u.run_id, u.attempt, u.model, u.input_tokens, u.output_tokens,
                   u.num_turns, u.duration_ms, u.cost_usd, u.created_at, u.purpose, u.success,
                   coalesce(u.job_id, r.job_id) AS job_id, r.status
            FROM agent_usage u
            LEFT JOIN resume_runs r ON r.id = u.run_id AND u.run_kind = 'resume'
            ORDER BY u.id DESC
            LIMIT 50
            """
        )
        recent = list(cursor.fetchall())
    count, cost, input_tokens, output_tokens = totals if totals else (0, 0, 0, 0)
    return {
        "days": days,
        "runs": int(count),
        "cost_usd": cost,
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "by_day": by_day,
        "recent": recent,
    }


def _active(conn: Connection[Any], job_id: int) -> int | None:
    row = conn.execute(
        """
        SELECT id FROM resume_runs
        WHERE job_id = %s AND status IN ('queued', 'running')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (job_id,),
    ).fetchone()
    return None if row is None else int(row[0])


def _dict_row(cursor: Any) -> Any:
    from psycopg.rows import dict_row

    return dict_row(cursor)
