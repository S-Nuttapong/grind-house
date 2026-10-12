"""All SQL for Job Hunt OS. Callers pass an open connection."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
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
    search_id: int | None = None,
) -> int:
    row = conn.execute(
        """
        INSERT INTO runs (scope_id, search_id, source_id, scraper_version)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (scope_id, search_id, source_id, scraper_version),
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
    skipped: int = 0,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE runs
        SET finished_at = now(), status = %s, fetched = %s, new_jobs = %s,
            updated = %s, closed = %s, skipped = %s, error = %s
        WHERE id = %s
        """,
        (status, fetched, new_jobs, updated, closed, skipped, error, run_id),
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
    role: str | None = None,
    industry: str | None = None,
) -> int:
    row = conn.execute(
        """
        INSERT INTO jobs (
          company_id, title, title_norm, level, role, industry, country, city, remote,
          tz_min, tz_max, employment_type, salary_min, salary_max, salary_currency,
          salary_interval, salary_usd_year_min, posted_at, apply_url, description_md, dedupe_key
        )
        VALUES (
          %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        RETURNING id
        """,
        (
            company_id,
            title,
            title_norm,
            level,
            role,
            industry,
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
    detail_status: str = "done",
) -> int:
    row = conn.execute(
        """
        INSERT INTO postings (
          job_id, source_id, source_job_id, source_url, content_hash,
          first_run_id, last_run_id, detail_status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (job_id, source_id, source_job_id, source_url, content_hash, run_id, run_id, detail_status),
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
    role: str | None = None,
    industry: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE jobs SET
          title = %s, title_norm = %s, level = %s, role = %s, industry = %s,
          country = %s, city = %s, remote = %s,
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
            role,
            industry,
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
    role: str | None = None,
    industry: str | None = None,
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
          role = COALESCE(role, %s),
          industry = COALESCE(industry, %s),
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
            role,
            industry,
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


def list_runs(conn: Connection[Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT r.id, r.source_id, r.status, r.fetched, r.new_jobs, r.updated, r.closed,
                   r.skipped, r.error, r.started_at, r.finished_at,
                   COALESCE(fs.name, s.name) AS scope_name
            FROM runs r
            LEFT JOIN fetch_scopes fs ON fs.id = r.scope_id
            LEFT JOIN searches s ON s.id = r.search_id
            ORDER BY r.started_at DESC
            LIMIT 40
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def alert_sources(conn: Connection[Any]) -> set[str]:
    """Sources whose last three runs were all partial or failed."""
    rows = conn.execute(
        """
        SELECT source_id FROM (
            SELECT source_id, status,
                   row_number() OVER (PARTITION BY source_id ORDER BY started_at DESC) AS n
            FROM runs
        ) recent
        WHERE n <= 3
        GROUP BY source_id
        HAVING count(*) = 3 AND bool_and(status IN ('partial', 'failed'))
        """
    ).fetchall()
    return {str(row[0]) for row in rows}


def list_searches(conn: Connection[Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, name, keywords, countries, timezone, enabled
            FROM searches
            ORDER BY id
            """
        )
        searches = [dict(row) for row in cursor.fetchall()]
        cursor.execute(
            """
            SELECT ss.search_id, ss.source_id, ss.poll_minutes, ss.paused_until, ss.strikes,
                   ss.enabled, ss.last_catchup_at,
                   max(sm.last_polled_at) AS last_polled_at,
                   (ARRAY_AGG(sm.last_status ORDER BY sm.last_polled_at DESC NULLS LAST))[1]
                     AS last_status
            FROM search_sources ss
            LEFT JOIN search_markets sm
              ON sm.search_id = ss.search_id AND sm.source_id = ss.source_id
            GROUP BY ss.search_id, ss.source_id
            ORDER BY ss.source_id
            """
        )
        grouped: dict[int, list[dict[str, Any]]] = {}
        for row in cursor.fetchall():
            item = dict(row)
            grouped.setdefault(int(item["search_id"]), []).append(item)
    for search in searches:
        search["countries"] = [str(code).strip() for code in search["countries"]]
        search["sources"] = grouped.get(int(search["id"]), [])
    return searches


def get_search(conn: Connection[Any], search_id: int) -> dict[str, Any] | None:
    found = [row for row in list_searches(conn) if int(row["id"]) == search_id]
    return found[0] if found else None


def insert_search(
    conn: Connection[Any],
    *,
    name: str,
    keywords: list[str],
    countries: list[str],
    timezone: str,
    enabled: bool,
) -> int:
    row = conn.execute(
        """
        INSERT INTO searches (name, keywords, countries, timezone, enabled)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (name, keywords, countries, timezone, enabled),
    ).fetchone()
    if row is None:
        raise RuntimeError("insert_search returned no id")
    return int(row[0])


def update_search(
    conn: Connection[Any],
    search_id: int,
    *,
    name: str,
    keywords: list[str],
    countries: list[str],
    timezone: str,
    enabled: bool,
) -> None:
    conn.execute(
        """
        UPDATE searches
        SET name = %s, keywords = %s, countries = %s, timezone = %s, enabled = %s
        WHERE id = %s
        """,
        (name, keywords, countries, timezone, enabled, search_id),
    )


def delete_search(conn: Connection[Any], search_id: int) -> bool:
    row = conn.execute("DELETE FROM searches WHERE id = %s RETURNING id", (search_id,)).fetchone()
    return row is not None


def replace_sources(
    conn: Connection[Any],
    search_id: int,
    sources: list[tuple[str, int, bool]],
) -> None:
    """Match the source list. Rows that stay keep their circuit-breaker state."""
    wanted = {source_id for source_id, _poll, _enabled in sources}
    conn.execute(
        """
        DELETE FROM search_sources
        WHERE search_id = %s AND NOT (source_id = ANY(%s))
        """,
        (search_id, list(wanted)),
    )
    for source_id, poll_minutes, enabled in sources:
        conn.execute(
            """
            INSERT INTO search_sources (search_id, source_id, poll_minutes, enabled)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (search_id, source_id)
            DO UPDATE SET poll_minutes = EXCLUDED.poll_minutes, enabled = EXCLUDED.enabled
            """,
            (search_id, source_id, poll_minutes, enabled),
        )


def source_min_seconds(conn: Connection[Any]) -> dict[str, int]:
    rows = conn.execute("SELECT id, extract(epoch FROM min_interval)::int FROM sources").fetchall()
    return {str(row[0]): int(row[1]) for row in rows}


def known_source(conn: Connection[Any], source_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM sources WHERE id = %s", (source_id,)).fetchone()
    return row is not None


def load_search_work(conn: Connection[Any], search_id: int | None) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT s.id AS search_id, s.name, s.keywords, s.countries, s.timezone,
                   ss.source_id, ss.poll_minutes, ss.strikes, ss.paused_until,
                   ss.last_catchup_at, ss.cursor
            FROM searches s
            JOIN search_sources ss ON ss.search_id = s.id
            WHERE s.enabled AND ss.enabled
              AND (ss.paused_until IS NULL OR ss.paused_until <= now())
              AND (%s::bigint IS NULL OR s.id = %s)
            ORDER BY ss.source_id, s.id
            """,
            (search_id, search_id),
        )
        return [dict(row) for row in cursor.fetchall()]


def ensure_market(conn: Connection[Any], search_id: int, source_id: str, country: str) -> None:
    conn.execute(
        """
        INSERT INTO search_markets (search_id, source_id, country)
        VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (search_id, source_id, country),
    )


def due_markets(
    conn: Connection[Any], search_id: int, source_id: str, poll_minutes: int
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT country, last_polled_at, last_status
            FROM search_markets
            WHERE search_id = %s AND source_id = %s
              AND (
                last_polled_at IS NULL
                OR last_polled_at <= now() - make_interval(mins => %s)
              )
            ORDER BY last_polled_at NULLS FIRST,
                     CASE country WHEN 'TH' THEN 0 WHEN 'SG' THEN 1 ELSE 2 END,
                     country
            """,
            (search_id, source_id, poll_minutes),
        )
        rows = [dict(row) for row in cursor.fetchall()]
    for row in rows:
        row["country"] = str(row["country"]).strip()
    return rows


def mark_market(
    conn: Connection[Any],
    search_id: int,
    source_id: str,
    country: str,
    status: str,
) -> None:
    conn.execute(
        """
        UPDATE search_markets
        SET last_polled_at = now(), last_status = %s
        WHERE search_id = %s AND source_id = %s AND country = %s
        """,
        (status, search_id, source_id, country),
    )


def mark_search_stale(conn: Connection[Any], search_id: int) -> None:
    conn.execute(
        """
        UPDATE search_markets SET last_polled_at = NULL
        WHERE search_id = %s
        """,
        (search_id,),
    )


def save_breaker(
    conn: Connection[Any],
    search_id: int,
    source_id: str,
    *,
    strikes: int,
    pause_minutes: int,
    cursor: dict[str, Any] | None,
    caught_up: bool,
) -> None:
    conn.execute(
        """
        UPDATE search_sources
        SET strikes = %s,
            paused_until = CASE WHEN %s > 0 THEN now() + make_interval(mins => %s) ELSE NULL END,
            cursor = %s,
            last_catchup_at = CASE WHEN %s THEN now() ELSE last_catchup_at END
        WHERE search_id = %s AND source_id = %s
        """,
        (
            strikes,
            pause_minutes,
            pause_minutes,
            Jsonb(cursor) if cursor else None,
            caught_up,
            search_id,
            source_id,
        ),
    )


def known_ids(conn: Connection[Any], source_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT source_job_id FROM postings WHERE source_id = %s",
        (source_id,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def allowed_roles(conn: Connection[Any]) -> list[str]:
    row = conn.execute("SELECT allowed_roles FROM scrape_settings WHERE id").fetchone()
    if row is None:
        return []
    return [str(role) for role in row[0]]


def save_allowed_roles(conn: Connection[Any], roles: list[str]) -> None:
    conn.execute("UPDATE scrape_settings SET allowed_roles = %s WHERE id", (roles,))


def due_scopes(conn: Connection[Any]) -> list[tuple[Any, ...]]:
    return list(
        conn.execute(
            """
            SELECT fs.id, fs.source_id, fs.cron, fs.timezone
            FROM fetch_scopes fs
            JOIN sources s ON s.id = fs.source_id
            WHERE fs.enabled AND s.kind = 'ats'
              AND (fs.next_run_at IS NULL OR fs.next_run_at <= now())
            ORDER BY fs.next_run_at NULLS FIRST, fs.id
            """
        ).fetchall()
    )


def advance_scope(conn: Connection[Any], scope_id: int, next_run_at: datetime) -> None:
    conn.execute(
        """
        UPDATE fetch_scopes
        SET last_run_at = now(), next_run_at = %s
        WHERE id = %s
        """,
        (next_run_at, scope_id),
    )


def close_stale_aggregators(conn: Connection[Any]) -> int:
    """Close jobs whose only fresh evidence is an aggregator posting past close_after."""
    row = conn.execute(
        """
        WITH closed AS (
            UPDATE jobs j
            SET closed_at = now()
            WHERE j.closed_at IS NULL
              AND EXISTS (
                SELECT 1 FROM postings p
                JOIN sources s ON s.id = p.source_id
                WHERE p.job_id = j.id AND s.kind = 'aggregator'
              )
              AND NOT EXISTS (
                SELECT 1 FROM postings p
                JOIN sources s ON s.id = p.source_id
                WHERE p.job_id = j.id
                  AND (
                    s.kind <> 'aggregator'
                    OR (s.close_after IS NOT NULL AND p.last_seen_at >= now() - s.close_after)
                  )
              )
            RETURNING j.id
        )
        SELECT count(*) FROM closed
        """
    ).fetchone()
    return int(row[0]) if row else 0


def closed_today(conn: Connection[Any]) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM tick_hooks
        WHERE name = 'aggregator-close'
          AND ran_at >= date_trunc('day', now() AT TIME ZONE 'Asia/Bangkok')
        """
    ).fetchone()
    return row is not None


def insert_hook(
    conn: Connection[Any],
    *,
    name: str,
    phase: str,
    exit_code: int | None,
    duration_ms: int,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO tick_hooks (name, phase, exit_code, duration_ms, error)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (name, phase, exit_code, duration_ms, error),
    )


def list_hooks(conn: Connection[Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, name, phase, exit_code, duration_ms, ran_at, error
            FROM tick_hooks
            ORDER BY ran_at DESC
            LIMIT 20
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def pending_sources(conn: Connection[Any]) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT p.source_id
        FROM postings p
        JOIN jobs j ON j.id = p.job_id
        WHERE p.detail_status = 'pending' AND p.detail_attempts < 3
          AND j.closed_at IS NULL
        """
    ).fetchall()
    return [str(row[0]) for row in rows]


def pending_details(conn: Connection[Any], source_id: str, limit: int) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT p.id AS posting_id, p.job_id, p.source_job_id, p.detail_attempts,
                   j.company_id, j.title
            FROM postings p
            JOIN jobs j ON j.id = p.job_id
            WHERE p.source_id = %s AND p.detail_status = 'pending' AND p.detail_attempts < 3
              AND j.closed_at IS NULL
            ORDER BY p.first_seen_at
            LIMIT %s
            """,
            (source_id, limit),
        )
        return [dict(row) for row in cursor.fetchall()]


def posting_host(conn: Connection[Any], posting_id: int) -> str | None:
    row = conn.execute(
        """
        SELECT payload->>'host' FROM raw_payloads
        WHERE posting_id = %s
        ORDER BY fetched_at DESC
        LIMIT 1
        """,
        (posting_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return str(row[0])


def finish_detail(
    conn: Connection[Any],
    *,
    posting_id: int,
    job_id: int,
    description_md: str | None,
    level: str | None,
    industry: str | None,
    apply_url: str | None,
) -> None:
    conn.execute(
        """
        UPDATE jobs
        SET description_md = COALESCE(%s, description_md),
            level = COALESCE(%s, level),
            industry = COALESCE(%s, industry),
            apply_url = COALESCE(%s, apply_url)
        WHERE id = %s
        """,
        (description_md, level, industry, apply_url, job_id),
    )
    conn.execute(
        """
        UPDATE postings
        SET detail_status = 'done', detail_attempts = detail_attempts + 1
        WHERE id = %s
        """,
        (posting_id,),
    )


def fail_detail(conn: Connection[Any], posting_id: int) -> None:
    conn.execute(
        """
        UPDATE postings
        SET detail_attempts = detail_attempts + 1,
            detail_status = CASE WHEN detail_attempts + 1 >= 3 THEN 'failed' ELSE 'pending' END
        WHERE id = %s
        """,
        (posting_id,),
    )
