"""Board queries. Sort columns come from a fixed whitelist."""

from datetime import date, datetime
from typing import Any
from urllib.parse import urlencode

from psycopg import Connection
from psycopg.rows import dict_row

PAGE_SIZE = 40
_SORTS = {
    "posted": "j.posted_at DESC NULLS LAST, j.id DESC",
    "first_seen": "j.first_seen_at DESC, j.id DESC",
}
_STATUSES = {"saved", "skipped", "applied"}
_LABELS = {"saved": "maybe", "skipped": "skip", "applied": "apply"}


def parse_filters(params: dict[str, str]) -> dict[str, Any]:
    sort = params.get("sort") or "posted"
    if sort not in _SORTS:
        sort = "posted"
    try:
        page = max(1, int(params.get("page") or "1"))
    except ValueError:
        page = 1
    return {
        "q": _blank(params.get("q")),
        "country": _blank(params.get("country")),
        "remote": _blank(params.get("remote")),
        "source": _blank(params.get("source")),
        "include_closed": params.get("include_closed") == "1",
        "sort": sort,
        "page": page,
    }


def list_jobs(conn: Connection[Any], filters: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    where, values = _where(filters)
    order = _SORTS[str(filters["sort"])]
    offset = (int(filters["page"]) - 1) * PAGE_SIZE
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"SELECT count(*) AS n FROM jobs j JOIN companies c ON c.id = j.company_id {where}",
            values,
        )
        total_row = cursor.fetchone()
        total = int(total_row["n"]) if total_row else 0
        cursor.execute(
            f"""
            SELECT j.id, j.title, c.name AS company, j.city, j.country, j.remote,
                   j.salary_min, j.salary_max, j.salary_currency, j.posted_at,
                   j.first_seen_at, j.closed_at, j.apply_url,
                   s.status,
                   (
                     SELECT string_agg(DISTINCT p.source_id, ', ' ORDER BY p.source_id)
                     FROM postings p WHERE p.job_id = j.id
                   ) AS sources
            FROM jobs j
            JOIN companies c ON c.id = j.company_id
            LEFT JOIN job_status s ON s.job_id = j.id
            {where}
            ORDER BY {order}
            LIMIT %s OFFSET %s
            """,
            (*values, PAGE_SIZE, offset),
        )
        rows = [_present(dict(row)) for row in cursor.fetchall()]
    return rows, total


def get_job(conn: Connection[Any], job_id: int) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT j.id, j.title, c.name AS company, j.city, j.country, j.remote,
                   j.salary_min, j.salary_max, j.salary_currency, j.posted_at,
                   j.first_seen_at, j.closed_at, j.apply_url, j.description_md,
                   s.status,
                   (
                     SELECT string_agg(DISTINCT p.source_id, ', ' ORDER BY p.source_id)
                     FROM postings p WHERE p.job_id = j.id
                   ) AS sources
            FROM jobs j
            JOIN companies c ON c.id = j.company_id
            LEFT JOIN job_status s ON s.job_id = j.id
            WHERE j.id = %s
            """,
            (job_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        job = _present(dict(row))
        cursor.execute(
            """
            SELECT source_id, source_url FROM postings WHERE job_id = %s ORDER BY source_id
            """,
            (job_id,),
        )
        job["postings"] = [dict(item) for item in cursor.fetchall()]
        cursor.execute(
            """
            SELECT status, reason, note, origin, at
            FROM job_events WHERE job_id = %s ORDER BY at DESC
            """,
            (job_id,),
        )
        job["events"] = [dict(item) for item in cursor.fetchall()]
    return job


def record_event(conn: Connection[Any], job_id: int, status: str, reason: str | None) -> None:
    if status not in _STATUSES:
        raise ValueError(f"unsupported status {status}")
    conn.execute(
        """
        INSERT INTO job_events (job_id, status, reason, origin)
        VALUES (%s, %s, %s, 'ui')
        """,
        (job_id, status, reason or None),
    )
    label = _LABELS[status]
    conn.execute(
        """
        INSERT INTO labels (job_id, label, origin)
        VALUES (%s, %s, 'ui_action')
        ON CONFLICT (job_id) DO UPDATE
          SET label = EXCLUDED.label, origin = EXCLUDED.origin, labeled_at = now()
        """,
        (job_id, label),
    )


def list_runs(conn: Connection[Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT r.id, r.source_id, r.status, r.fetched, r.new_jobs, r.updated, r.closed,
                   r.error, r.started_at, r.finished_at, fs.name AS scope_name
            FROM runs r
            LEFT JOIN fetch_scopes fs ON fs.id = r.scope_id
            ORDER BY r.started_at DESC
            LIMIT 40
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def filter_query(filters: dict[str, Any], *, page: int | None = None) -> str:
    pairs = {
        "q": filters["q"] or "",
        "country": filters["country"] or "",
        "remote": filters["remote"] or "",
        "source": filters["source"] or "",
        "include_closed": "1" if filters["include_closed"] else "",
        "sort": filters["sort"],
        "page": page if page is not None else filters["page"],
    }
    return urlencode({key: value for key, value in pairs.items() if value not in ("", None)})


def _where(filters: dict[str, Any]) -> tuple[str, tuple[Any, ...]]:
    clauses = ["TRUE"]
    values: list[Any] = []
    if not filters["include_closed"]:
        clauses.append("j.closed_at IS NULL")
    if filters["q"]:
        clauses.append("j.search @@ websearch_to_tsquery('english', %s)")
        values.append(filters["q"])
    if filters["country"]:
        clauses.append("j.country = %s")
        values.append(str(filters["country"]).upper())
    if filters["remote"]:
        clauses.append("j.remote = %s")
        values.append(filters["remote"])
    if filters["source"]:
        clauses.append(
            "EXISTS (SELECT 1 FROM postings p WHERE p.job_id = j.id AND p.source_id = %s)"
        )
        values.append(filters["source"])
    return "WHERE " + " AND ".join(clauses), tuple(values)


def _present(row: dict[str, Any]) -> dict[str, Any]:
    row["salary_label"] = _salary(row)
    row["place"] = ", ".join(part for part in (row.get("city"), row.get("country")) if part)
    row["age"] = _age(row.get("posted_at"), row.get("first_seen_at"))
    row["stage"] = row.get("status") or "not scored"
    return row


def _salary(row: dict[str, Any]) -> str | None:
    low = row.get("salary_min")
    high = row.get("salary_max")
    if low is None and high is None:
        return None
    currency = row.get("salary_currency") or ""
    if low is not None and high is not None:
        amount = f"{_as_int(low):,}–{_as_int(high):,}"
    elif low is not None:
        amount = f"{_as_int(low):,}+"
    elif high is not None:
        amount = f"up to {_as_int(high):,}"
    else:
        return None
    return f"{amount} {currency}".strip()


def _age(posted: object, first_seen: object) -> str:
    anchor: date | None
    if isinstance(posted, datetime):
        anchor = posted.date()
    elif isinstance(posted, date):
        anchor = posted
    elif isinstance(first_seen, datetime):
        anchor = first_seen.date()
    elif isinstance(first_seen, date):
        anchor = first_seen
    else:
        return ""
    days = (date.today() - anchor).days
    if days <= 0:
        return "today"
    return f"{days}d"


def _blank(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return int(str(value))
    return int(value)
