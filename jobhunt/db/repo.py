"""All SQL for Job Hunt OS. Callers pass an open connection."""

from datetime import date, datetime
from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb


def insert_company(
    conn: Connection[Any],
    *,
    name: str,
    name_norm: str,
    tier: str | None = None,
    careers_url: str | None = None,
    ats: str | None = None,
    ats_slug: str | None = None,
) -> int:
    row = conn.execute(
        """
        INSERT INTO companies (name, name_norm, tier, careers_url, ats, ats_slug)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (name, name_norm, tier, careers_url, ats, ats_slug),
    ).fetchone()
    if row is None:
        raise RuntimeError("insert_company returned no id")
    return int(row[0])


def get_company_by_name_norm(conn: Connection[Any], name_norm: str) -> tuple[Any, ...] | None:
    return conn.execute(
        """
        SELECT id, name, name_norm, tier, ats, ats_slug, careers_url, excluded
        FROM companies
        WHERE name_norm = %s
        """,
        (name_norm,),
    ).fetchone()


def insert_alias(conn: Connection[Any], alias_norm: str, company_id: int) -> None:
    conn.execute(
        """
        INSERT INTO company_aliases (alias_norm, company_id)
        VALUES (%s, %s)
        ON CONFLICT (alias_norm) DO NOTHING
        """,
        (alias_norm, company_id),
    )


def insert_scope(
    conn: Connection[Any],
    *,
    name: str,
    source_id: str,
    params: dict[str, Any],
    cron: str,
    timezone: str = "Asia/Bangkok",
) -> int:
    row = conn.execute(
        """
        INSERT INTO fetch_scopes (name, source_id, params, cron, timezone)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (name, source_id, Jsonb(params), cron, timezone),
    ).fetchone()
    if row is None:
        raise RuntimeError("insert_scope returned no id")
    return int(row[0])


def get_scope(conn: Connection[Any], scope_id: int) -> tuple[Any, ...] | None:
    return conn.execute(
        """
        SELECT id, name, source_id, params, cron, timezone, enabled
        FROM fetch_scopes
        WHERE id = %s
        """,
        (scope_id,),
    ).fetchone()


def start_run(
    conn: Connection[Any],
    *,
    source_id: str,
    scraper_version: str,
    scope_id: int | None = None,
) -> int:
    row = conn.execute(
        """
        INSERT INTO runs (scope_id, source_id, scraper_version)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (scope_id, source_id, scraper_version),
    ).fetchone()
    if row is None:
        raise RuntimeError("start_run returned no id")
    return int(row[0])


def finish_run(
    conn: Connection[Any],
    run_id: int,
    *,
    status: str,
    fetched: int = 0,
    new_jobs: int = 0,
    updated: int = 0,
    closed: int = 0,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE runs
        SET finished_at = now(), status = %s, fetched = %s, new_jobs = %s,
            updated = %s, closed = %s, error = %s
        WHERE id = %s
        """,
        (status, fetched, new_jobs, updated, closed, error, run_id),
    )


def insert_job(
    conn: Connection[Any],
    *,
    company_id: int,
    title: str,
    title_norm: str,
    apply_url: str,
    dedupe_key: str,
    level: str = "unknown",
    country: str | None = None,
    city: str | None = None,
    remote: str = "unknown",
    posted_at: date | None = None,
    description_md: str | None = None,
) -> int:
    row = conn.execute(
        """
        INSERT INTO jobs (
          company_id, title, title_norm, level, country, city, remote,
          posted_at, apply_url, description_md, dedupe_key
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            company_id,
            title,
            title_norm,
            level,
            country,
            city,
            remote,
            posted_at,
            apply_url,
            description_md,
            dedupe_key,
        ),
    ).fetchone()
    if row is None:
        raise RuntimeError("insert_job returned no id")
    return int(row[0])


def get_job(conn: Connection[Any], job_id: int) -> tuple[Any, ...] | None:
    return conn.execute(
        """
        SELECT id, company_id, title, title_norm, apply_url, dedupe_key, closed_at
        FROM jobs
        WHERE id = %s
        """,
        (job_id,),
    ).fetchone()


def insert_posting(
    conn: Connection[Any],
    *,
    job_id: int,
    source_id: str,
    source_job_id: str,
    source_url: str,
    content_hash: str,
    run_id: int | None = None,
) -> int:
    row = conn.execute(
        """
        INSERT INTO postings (
          job_id, source_id, source_job_id, source_url, content_hash, first_run_id, last_run_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (job_id, source_id, source_job_id, source_url, content_hash, run_id, run_id),
    ).fetchone()
    if row is None:
        raise RuntimeError("insert_posting returned no id")
    return int(row[0])


def get_posting(
    conn: Connection[Any], source_id: str, source_job_id: str
) -> tuple[Any, ...] | None:
    return conn.execute(
        """
        SELECT id, job_id, source_id, source_job_id, source_url, content_hash
        FROM postings
        WHERE source_id = %s AND source_job_id = %s
        """,
        (source_id, source_job_id),
    ).fetchone()


def insert_raw_payload(
    conn: Connection[Any],
    *,
    posting_id: int,
    run_id: int,
    payload: dict[str, Any],
    fetched_at: datetime | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO raw_payloads (posting_id, run_id, payload, fetched_at)
        VALUES (%s, %s, %s, coalesce(%s, now()))
        """,
        (posting_id, run_id, Jsonb(payload), fetched_at),
    )
