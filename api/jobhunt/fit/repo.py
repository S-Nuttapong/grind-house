"""SQL for the job fit pipeline. Callers pass an open connection."""

from datetime import datetime
from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb


def upsert_fit_source(
    conn: Connection[Any], *, source_hash: str, kind: str, resume_id: int | None
) -> None:
    conn.execute(
        """
        INSERT INTO fit_sources (hash, kind, resume_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (hash) DO NOTHING
        """,
        (source_hash, kind, resume_id),
    )


def mark_source_scored(conn: Connection[Any], source_hash: str) -> None:
    conn.execute("UPDATE fit_sources SET scored_at = now() WHERE hash = %s", (source_hash,))


def latest_scored_source(conn: Connection[Any], kind: str) -> str | None:
    row = conn.execute(
        """
        SELECT hash FROM fit_sources
        WHERE kind = %s AND scored_at IS NOT NULL
        ORDER BY scored_at DESC
        LIMIT 1
        """,
        (kind,),
    ).fetchone()
    return None if row is None else str(row[0])


def has_unscored_jobs(conn: Connection[Any], model_id: str, source_hash: str) -> bool:
    """True when an open job has no score for this source, or its text changed.

    The digest matches job_hash(): sha256 of the title, a newline, and the
    description, which is empty when the description is missing.
    """
    row = conn.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM jobs j
            LEFT JOIN job_fits f
              ON f.job_id = j.id AND f.model_id = %s AND f.source_hash = %s
            WHERE j.closed_at IS NULL
              AND (
                f.job_id IS NULL
                OR f.job_hash <> encode(digest(convert_to(
                     j.title || chr(10) || coalesce(j.description_md, ''), 'UTF8'
                   ), 'sha256'), 'hex')
              )
        )
        """,
        (model_id, source_hash),
    ).fetchone()
    return bool(row and row[0])


def upsert_job_fit(conn: Connection[Any], fit: dict[str, Any]) -> None:
    row = {**fit, "coverage": fit.get("coverage"), "gaps": fit.get("gaps") or []}
    conn.execute(
        """
        INSERT INTO job_fits (
            job_id, model_id, source_hash, job_hash, score, raw, coverage, gaps,
            matched_terms, missing_terms
        )
        VALUES (
            %(job_id)s, %(model_id)s, %(source_hash)s, %(job_hash)s, %(score)s, %(raw)s,
            %(coverage)s, %(gaps)s, %(matched_terms)s, %(missing_terms)s
        )
        ON CONFLICT (job_id, model_id, source_hash) DO UPDATE SET
            job_hash = EXCLUDED.job_hash, score = EXCLUDED.score, raw = EXCLUDED.raw,
            coverage = EXCLUDED.coverage, gaps = EXCLUDED.gaps,
            matched_terms = EXCLUDED.matched_terms, missing_terms = EXCLUDED.missing_terms,
            computed_at = now()
        """,
        row,
    )


def replace_matches(
    conn: Connection[Any],
    *,
    job_id: int,
    model_id: str,
    source_hash: str,
    matches: list[dict[str, Any]],
) -> None:
    """Replace the selected docs for one fit row. The fit row must already exist."""
    conn.execute(
        """
        DELETE FROM job_fit_matches
        WHERE job_id = %s AND model_id = %s AND source_hash = %s
        """,
        (job_id, model_id, source_hash),
    )
    for rank, match in enumerate(matches, start=1):
        similarity = max(0.0, min(1.0, float(match["similarity"])))
        conn.execute(
            """
            INSERT INTO job_fit_matches (
                job_id, model_id, source_hash, rank, doc_ref, aspect, similarity
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (job_id, model_id, source_hash, rank, match["doc_ref"], match["aspect"], similarity),
        )


def matches_for(
    conn: Connection[Any], job_id: int, model_id: str, source_hash: str
) -> list[dict[str, Any]]:
    """Selected docs in rank order. Titles come from brag_docs when the id is one."""
    cursor = conn.execute(
        """
        SELECT m.doc_ref, m.aspect, m.similarity, b.title
        FROM job_fit_matches m
        LEFT JOIN brag_docs b ON b.id = m.doc_ref
        WHERE m.job_id = %s AND m.model_id = %s AND m.source_hash = %s
        ORDER BY m.rank
        """,
        (job_id, model_id, source_hash),
    )
    rows: list[dict[str, Any]] = []
    for doc_ref, aspect, similarity, title in cursor.fetchall():
        rows.append(
            {
                "id": str(doc_ref),
                "title": str(title) if title else _match_title(str(doc_ref)),
                "aspect": str(aspect),
                "similarity": float(similarity),
            }
        )
    return rows


def _match_title(doc_ref: str) -> str:
    if doc_ref == "profile":
        return "Profile"
    if doc_ref.startswith("resume:"):
        return "Resume"
    return doc_ref


def list_schedules(conn: Connection[Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute("SELECT * FROM fit_schedules ORDER BY id")
        return list(cursor.fetchall())


def schedule_id_for_mode(conn: Connection[Any], mode: str) -> int | None:
    """The schedule a manual run of this mode belongs to. Enabled wins, then oldest."""
    row = conn.execute(
        """
        SELECT id FROM fit_schedules
        WHERE mode = %s
        ORDER BY enabled DESC, id
        LIMIT 1
        """,
        (mode,),
    ).fetchone()
    return None if row is None else int(row[0])


def latest_run_by_schedule(conn: Connection[Any]) -> dict[int, dict[str, Any]]:
    """Newest run for each schedule: its own runs, or a manual run of the same mode."""
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute(
            """
            SELECT DISTINCT ON (s.id)
                   s.id AS schedule_key,
                   r.*
            FROM fit_schedules s
            JOIN fit_runs r
              ON r.schedule_id = s.id
              OR (r.schedule_id IS NULL AND r.mode = s.mode)
            ORDER BY s.id, coalesce(r.finished_at, r.started_at, r.queued_at) DESC, r.id DESC
            """
        )
        found: dict[int, dict[str, Any]] = {}
        for row in cursor.fetchall():
            schedule_id = int(row.pop("schedule_key"))
            found[schedule_id] = row
        return found


def record_finished_run(conn: Connection[Any], run: dict[str, Any]) -> int:
    """Store a run that already finished, such as one started from the command line."""
    row = conn.execute(
        """
        INSERT INTO fit_runs (
            schedule_id, mode, trigger, model_id, status, scored, skipped, error,
            idempotency_key, queued_at, started_at, finished_at
        )
        VALUES (
            %(schedule_id)s, %(mode)s, %(trigger)s, %(model_id)s, %(status)s,
            %(scored)s, %(skipped)s, %(error)s, %(idempotency_key)s,
            %(started_at)s, %(started_at)s, %(finished_at)s
        )
        ON CONFLICT (idempotency_key) DO NOTHING
        RETURNING id
        """,
        run,
    ).fetchone()
    if row is not None:
        return int(row[0])
    existing = conn.execute(
        "SELECT id FROM fit_runs WHERE idempotency_key = %s", (run["idempotency_key"],)
    ).fetchone()
    if existing is None:
        raise RuntimeError("record_finished_run lost the idempotency row")
    return int(existing[0])


def get_schedule(conn: Connection[Any], schedule_id: int) -> dict[str, Any] | None:
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute("SELECT * FROM fit_schedules WHERE id = %s", (schedule_id,))
        row = cursor.fetchone()
    return dict(row) if row else None


def insert_schedule(conn: Connection[Any], schedule: dict[str, Any]) -> int:
    row = conn.execute(
        """
        INSERT INTO fit_schedules (name, mode, cron, timezone, enabled, next_run_at)
        VALUES (%(name)s, %(mode)s, %(cron)s, %(timezone)s, %(enabled)s, %(next_run_at)s)
        RETURNING id
        """,
        schedule,
    ).fetchone()
    if row is None:
        raise RuntimeError("insert_schedule returned no id")
    return int(row[0])


def update_schedule(conn: Connection[Any], schedule_id: int, fields: dict[str, Any]) -> bool:
    assignments = ", ".join(f"{column} = %({column})s" for column in fields)
    updated = conn.execute(
        f"UPDATE fit_schedules SET {assignments}, updated_at = now() WHERE id = %(id)s",
        {**fields, "id": schedule_id},
    ).rowcount
    return updated > 0


def delete_schedule(conn: Connection[Any], schedule_id: int) -> bool:
    deleted = conn.execute("DELETE FROM fit_schedules WHERE id = %s", (schedule_id,)).rowcount
    return deleted > 0


def due_schedules(conn: Connection[Any], now: datetime) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute(
            """
            SELECT * FROM fit_schedules
            WHERE enabled AND (next_run_at IS NULL OR next_run_at <= %s)
            ORDER BY next_run_at NULLS FIRST
            """,
            (now,),
        )
        return list(cursor.fetchall())


def enqueue_run(conn: Connection[Any], run: dict[str, Any]) -> tuple[int, bool]:
    """Insert a queued run. Returns (id, created); created is false when the key exists."""
    row = conn.execute(
        """
        INSERT INTO fit_runs (schedule_id, mode, trigger, model_id, idempotency_key)
        VALUES (%(schedule_id)s, %(mode)s, %(trigger)s, %(model_id)s, %(idempotency_key)s)
        ON CONFLICT (idempotency_key) DO NOTHING
        RETURNING id
        """,
        run,
    ).fetchone()
    if row is not None:
        return int(row[0]), True
    existing = conn.execute(
        "SELECT id FROM fit_runs WHERE idempotency_key = %s", (run["idempotency_key"],)
    ).fetchone()
    if existing is None:
        raise RuntimeError("enqueue_run lost the idempotency row")
    return int(existing[0]), False


def has_queued_scrape_run(conn: Connection[Any], mode: str, model_id: str) -> bool:
    """True when a scrape run is waiting. A stuck running row must not block the next one."""
    row = conn.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM fit_runs
            WHERE status = 'queued' AND trigger = 'scrape' AND mode = %s AND model_id = %s
        )
        """,
        (mode, model_id),
    ).fetchone()
    return bool(row and row[0])


def claim_run(conn: Connection[Any]) -> dict[str, Any] | None:
    """Claim the oldest queued run. Safe for two workers at once (SKIP LOCKED)."""
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute(
            """
            UPDATE fit_runs SET status = 'running', started_at = coalesce(started_at, now())
            WHERE id = (
                SELECT id FROM fit_runs
                WHERE status = 'queued'
                -- A scheduled run the user is waiting on beats the scrape sweep.
                ORDER BY (trigger = 'scrape'), queued_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING *
            """
        )
        row = cursor.fetchone()
    return dict(row) if row else None


def finish_fit_run(
    conn: Connection[Any], run_id: int, *, status: str, scored: int, skipped: int, error: str | None
) -> None:
    conn.execute(
        """
        UPDATE fit_runs
        SET status = %s, scored = %s, skipped = %s, error = %s, finished_at = now()
        WHERE id = %s
        """,
        (status, scored, skipped, error, run_id),
    )


def requeue_run(conn: Connection[Any], run_id: int) -> None:
    conn.execute(
        "UPDATE fit_runs SET status = 'queued', finished_at = NULL WHERE id = %s", (run_id,)
    )


def add_run_event(conn: Connection[Any], run_id: int, kind: str, payload: dict[str, Any]) -> int:
    row = conn.execute(
        """
        INSERT INTO fit_run_events (run_id, kind, payload)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (run_id, kind, Jsonb(payload)),
    ).fetchone()
    if row is None:
        raise RuntimeError("add_run_event returned no id")
    return int(row[0])


def notify_run(conn: Connection[Any], run_id: int, event_id: int) -> None:
    conn.execute("SELECT pg_notify(%s, %s)", (f"fit_run_{run_id}", str(event_id)))


def list_runs(conn: Connection[Any], limit: int = 20) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute("SELECT * FROM fit_runs ORDER BY queued_at DESC LIMIT %s", (limit,))
        return list(cursor.fetchall())


def get_run(conn: Connection[Any], run_id: int) -> dict[str, Any] | None:
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute("SELECT * FROM fit_runs WHERE id = %s", (run_id,))
        row = cursor.fetchone()
    return dict(row) if row else None


def run_events_after(conn: Connection[Any], run_id: int, after_id: int) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute(
            """
            SELECT * FROM fit_run_events
            WHERE run_id = %s AND id > %s
            ORDER BY id
            """,
            (run_id, after_id),
        )
        return list(cursor.fetchall())


def latest_progress(conn: Connection[Any], run_id: int) -> dict[str, Any] | None:
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute(
            """
            SELECT * FROM fit_run_events
            WHERE run_id = %s AND kind = 'progress'
            ORDER BY id DESC
            LIMIT 1
            """,
            (run_id,),
        )
        row = cursor.fetchone()
    return dict(row) if row else None


def heartbeat(conn: Connection[Any], model_id: str) -> None:
    conn.execute("UPDATE fit_worker SET model_id = %s, heartbeat_at = now()", (model_id,))


def worker_status(conn: Connection[Any]) -> dict[str, Any]:
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute("SELECT model_id, heartbeat_at FROM fit_worker")
        row = cursor.fetchone()
    return dict(row) if row else {"model_id": None, "heartbeat_at": None}


def _dict_row(cursor: Any) -> Any:
    from psycopg.rows import dict_row

    return dict_row(cursor)
