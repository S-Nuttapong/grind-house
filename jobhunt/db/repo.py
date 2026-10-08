"""All SQL for Job Hunt OS. Callers pass an open connection."""

from datetime import date, datetime
from decimal import Decimal
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
    tz_min: int | None = None,
    tz_max: int | None = None,
    employment_type: str | None = None,
    salary_min: Decimal | None = None,
    salary_max: Decimal | None = None,
    salary_currency: str | None = None,
    salary_interval: str | None = None,
    salary_usd_year_min: Decimal | None = None,
    posted_at: date | None = None,
    description_md: str | None = None,
) -> int:
    row = conn.execute(
        """
        INSERT INTO jobs (
          company_id, title, title_norm, level, country, city, remote,
          tz_min, tz_max, employment_type, salary_min, salary_max, salary_currency,
          salary_interval, salary_usd_year_min, posted_at, apply_url, description_md, dedupe_key
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            tz_min,
            tz_max,
            employment_type,
            salary_min,
            salary_max,
            salary_currency,
            salary_interval,
            salary_usd_year_min,
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


def get_company_by_ats(conn: Connection[Any], ats: str, ats_slug: str) -> tuple[Any, ...] | None:
    return conn.execute(
        """
        SELECT id, name, name_norm, tier, ats, ats_slug
        FROM companies
        WHERE ats = %s AND ats_slug = %s
        """,
        (ats, ats_slug),
    ).fetchone()


def get_alias_company_id(conn: Connection[Any], alias_norm: str) -> int | None:
    row = conn.execute(
        "SELECT company_id FROM company_aliases WHERE alias_norm = %s",
        (alias_norm,),
    ).fetchone()
    if row is None:
        return None
    return int(row[0])


def clear_company_ats(conn: Connection[Any], company_id: int) -> None:
    conn.execute(
        "UPDATE companies SET ats = NULL, ats_slug = NULL WHERE id = %s",
        (company_id,),
    )


def list_ats_companies(conn: Connection[Any], source_id: str) -> list[tuple[Any, ...]]:
    return list(
        conn.execute(
            """
            SELECT id, name, ats_slug, tier
            FROM companies
            WHERE ats = %s AND ats_slug IS NOT NULL AND excluded = false
            ORDER BY id
            """,
            (source_id,),
        ).fetchall()
    )


def touch_posting(
    conn: Connection[Any], posting_id: int, *, run_id: int, content_hash: str, source_url: str
) -> None:
    conn.execute(
        """
        UPDATE postings
        SET last_seen_at = now(), last_run_id = %s, content_hash = %s, source_url = %s
        WHERE id = %s
        """,
        (run_id, content_hash, source_url, posting_id),
    )


def touch_job(conn: Connection[Any], job_id: int) -> None:
    conn.execute(
        "UPDATE jobs SET last_seen_at = now(), closed_at = NULL WHERE id = %s",
        (job_id,),
    )


def update_job_content(
    conn: Connection[Any],
    job_id: int,
    *,
    title: str,
    title_norm: str,
    level: str,
    country: str | None,
    city: str | None,
    remote: str,
    tz_min: int | None,
    tz_max: int | None,
    employment_type: str | None,
    salary_min: Decimal | None,
    salary_max: Decimal | None,
    salary_currency: str | None,
    salary_interval: str | None,
    salary_usd_year_min: Decimal | None,
    posted_at: date | None,
    description_md: str | None,
    dedupe_key: str,
    apply_url: str,
) -> None:
    conn.execute(
        """
        UPDATE jobs SET
          title = %s, title_norm = %s, level = %s, country = %s, city = %s, remote = %s,
          tz_min = %s, tz_max = %s, employment_type = %s,
          salary_min = %s, salary_max = %s, salary_currency = %s, salary_interval = %s,
          salary_usd_year_min = %s, posted_at = %s, description_md = %s, dedupe_key = %s,
          apply_url = %s, last_seen_at = now(), closed_at = NULL
        WHERE id = %s
        """,
        (
            title,
            title_norm,
            level,
            country,
            city,
            remote,
            tz_min,
            tz_max,
            employment_type,
            salary_min,
            salary_max,
            salary_currency,
            salary_interval,
            salary_usd_year_min,
            posted_at,
            description_md,
            dedupe_key,
            apply_url,
            job_id,
        ),
    )


def fill_job_gaps(
    conn: Connection[Any],
    job_id: int,
    *,
    salary_min: Decimal | None,
    salary_max: Decimal | None,
    salary_currency: str | None,
    salary_interval: str | None,
    salary_usd_year_min: Decimal | None,
    posted_at: date | None,
    remote: str,
    tz_min: int | None,
    tz_max: int | None,
) -> None:
    conn.execute(
        """
        UPDATE jobs SET
          salary_min = COALESCE(salary_min, %s),
          salary_max = COALESCE(salary_max, %s),
          salary_currency = COALESCE(salary_currency, %s),
          salary_interval = COALESCE(salary_interval, %s),
          salary_usd_year_min = COALESCE(salary_usd_year_min, %s),
          posted_at = COALESCE(posted_at, %s),
          remote = CASE WHEN remote = 'unknown' THEN %s ELSE remote END,
          tz_min = COALESCE(tz_min, %s),
          tz_max = COALESCE(tz_max, %s),
          last_seen_at = now()
        WHERE id = %s
        """,
        (
            salary_min,
            salary_max,
            salary_currency,
            salary_interval,
            salary_usd_year_min,
            posted_at,
            remote,
            tz_min,
            tz_max,
            job_id,
        ),
    )


def set_apply_url(conn: Connection[Any], job_id: int, apply_url: str) -> None:
    conn.execute("UPDATE jobs SET apply_url = %s WHERE id = %s", (apply_url, job_id))


def find_open_duplicate(
    conn: Connection[Any],
    *,
    company_id: int,
    title_norm: str,
    country: str | None,
    dedupe_key: str,
    threshold: float,
) -> int | None:
    row = conn.execute(
        """
        SELECT id
        FROM jobs
        WHERE company_id = %s AND closed_at IS NULL
          AND (
            dedupe_key = %s
            OR (
              coalesce(country, '??') = coalesce(%s, '??')
              AND title_norm %% %s
              AND similarity(title_norm, %s) >= %s
              AND last_seen_at > now() - interval '14 days'
            )
          )
        ORDER BY (dedupe_key = %s) DESC, similarity(title_norm, %s) DESC
        LIMIT 1
        """,
        (
            company_id,
            dedupe_key,
            country,
            title_norm,
            title_norm,
            threshold,
            dedupe_key,
            title_norm,
        ),
    ).fetchone()
    if row is None:
        return None
    return int(row[0])


def job_has_ats_posting(conn: Connection[Any], job_id: int) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM postings p
        JOIN sources s ON s.id = p.source_id
        WHERE p.job_id = %s AND s.kind = 'ats'
        LIMIT 1
        """,
        (job_id,),
    ).fetchone()
    return row is not None


def close_missing(conn: Connection[Any], company_id: int, source_id: str, run_id: int) -> int:
    rows = conn.execute(
        """
        UPDATE jobs j SET closed_at = now()
        WHERE j.company_id = %s AND j.closed_at IS NULL
          AND EXISTS (
            SELECT 1 FROM postings p WHERE p.job_id = j.id AND p.source_id = %s
          )
          AND NOT EXISTS (
            SELECT 1 FROM postings p
            WHERE p.job_id = j.id
              AND (
                p.last_run_id = %s
                OR (p.source_id <> %s AND p.last_seen_at > now() - interval '14 days')
              )
          )
        RETURNING j.id
        """,
        (company_id, source_id, run_id, source_id),
    ).fetchall()
    return len(rows)


def source_kind(conn: Connection[Any], source_id: str) -> str | None:
    row = conn.execute("SELECT kind FROM sources WHERE id = %s", (source_id,)).fetchone()
    if row is None:
        return None
    return str(row[0])


def list_scopes_for_source(conn: Connection[Any], source_id: str) -> list[tuple[Any, ...]]:
    return list(
        conn.execute(
            """
            SELECT id, name, source_id, params, cron, timezone, enabled
            FROM fetch_scopes
            WHERE source_id = %s AND enabled
            ORDER BY id
            """,
            (source_id,),
        ).fetchall()
    )


def scope_exists(conn: Connection[Any], name: str) -> bool:
    row = conn.execute("SELECT 1 FROM fetch_scopes WHERE name = %s", (name,)).fetchone()
    return row is not None


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
