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
_POSTED_WITHIN = {1, 3, 7, 14}
_STATUSES = {"saved", "skipped", "applied"}
_LABELS = {"saved": "maybe", "skipped": "skip", "applied": "apply"}
_REMOTE_LABELS = {
    "remote": "Remote",
    "hybrid": "Hybrid",
    "onsite": "On-site",
    "unknown": "Workplace unknown",
}
_MISSING = object()
PIPELINE_STATUSES = ("saved", "applied", "skipped")
_SCORE_COLUMNS = (
    "m.score, m.band, pf.passed_hard, pf.filter_reason, pf.shortlisted, pf.job_id AS prefiltered"
)
_SCORE_JOINS = """
            LEFT JOIN LATERAL (
              SELECT mm.score, mm.band FROM matches mm
              WHERE mm.job_id = j.id ORDER BY mm.created_at DESC LIMIT 1
            ) m ON TRUE
            LEFT JOIN prefilter pf ON pf.job_id = j.id"""


def parse_filters(params: dict[str, str]) -> dict[str, Any]:
    sort = params.get("sort") or "posted"
    if sort not in _SORTS:
        sort = "posted"
    try:
        page = max(1, int(params.get("page") or "1"))
    except ValueError:
        page = 1
    posted_raw = _blank(params.get("posted_within"))
    posted_within = int(posted_raw) if posted_raw and posted_raw.isdigit() else None
    if posted_within not in _POSTED_WITHIN:
        posted_within = None
    jk_raw = _blank(params.get("jk"))
    return {
        "q": _blank(params.get("q")),
        "where": _blank(params.get("where")),
        "country": _blank(params.get("country")),
        "remote": _blank(params.get("remote")),
        "source": _blank(params.get("source")),
        "posted_within": posted_within,
        "has_salary": params.get("has_salary") == "1",
        "include_closed": params.get("include_closed") == "1",
        "jk": int(jk_raw) if jk_raw and jk_raw.isdigit() else None,
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
                   j.employment_type, j.salary_min, j.salary_max, j.salary_currency,
                   j.posted_at, j.first_seen_at, j.closed_at, j.apply_url,
                   s.status, {_SCORE_COLUMNS},
                   left(
                     regexp_replace(coalesce(j.description_md, ''), '[[:punct:]]+', ' ', 'g'),
                     220
                   ) AS snippet,
                   (
                     SELECT string_agg(DISTINCT p.source_id, ', ' ORDER BY p.source_id)
                     FROM postings p WHERE p.job_id = j.id
                   ) AS sources
            FROM jobs j
            JOIN companies c ON c.id = j.company_id
            LEFT JOIN job_status s ON s.job_id = j.id
            {_SCORE_JOINS}
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
            f"""
            SELECT j.id, j.title, c.name AS company, j.city, j.country, j.remote,
                   j.employment_type, j.salary_min, j.salary_max, j.salary_currency,
                   j.posted_at, j.first_seen_at, j.closed_at, j.apply_url, j.description_md,
                   s.status, {_SCORE_COLUMNS},
                   (
                     SELECT string_agg(DISTINCT p.source_id, ', ' ORDER BY p.source_id)
                     FROM postings p WHERE p.job_id = j.id
                   ) AS sources
            FROM jobs j
            JOIN companies c ON c.id = j.company_id
            LEFT JOIN job_status s ON s.job_id = j.id
            {_SCORE_JOINS}
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
    job["tailor_prompt"] = (
        f"Tailor my resume for jobhunt job #{job['id']} — {job['company']} · {job['title']}"
    )
    return job


def list_pipeline(conn: Connection[Any]) -> dict[str, list[dict[str, Any]]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"""
            SELECT j.id, j.title, c.name AS company, j.city, j.country, j.remote,
                   j.employment_type, j.salary_min, j.salary_max, j.salary_currency,
                   j.posted_at, j.first_seen_at, j.closed_at, j.apply_url,
                   s.status, s.at AS status_at, {_SCORE_COLUMNS},
                   '' AS snippet,
                   (
                     SELECT string_agg(DISTINCT p.source_id, ', ' ORDER BY p.source_id)
                     FROM postings p WHERE p.job_id = j.id
                   ) AS sources
            FROM job_status s
            JOIN jobs j ON j.id = s.job_id
            JOIN companies c ON c.id = j.company_id
            {_SCORE_JOINS}
            WHERE s.status = ANY(%s)
            ORDER BY s.at DESC
            LIMIT 300
            """,
            (list(PIPELINE_STATUSES),),
        )
        rows = [_present(dict(row)) for row in cursor.fetchall()]
    columns: dict[str, list[dict[str, Any]]] = {status: [] for status in PIPELINE_STATUSES}
    for row in rows:
        columns[str(row["status"])].append(row)
    return columns


def list_facets(conn: Connection[Any]) -> dict[str, list[str]]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT DISTINCT source_id FROM postings ORDER BY source_id")
        sources = [str(row[0]) for row in cursor.fetchall()]
    return {"sources": sources, "remote": list(_REMOTE_LABELS)}


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


def filter_query(
    filters: dict[str, Any],
    *,
    page: int | None = None,
    jk: int | None | object = _MISSING,
) -> str:
    page_value = filters["page"] if page is None else page
    chosen_jk = filters.get("jk") if jk is _MISSING else jk
    pairs: dict[str, object] = {
        "q": filters.get("q") or "",
        "where": filters.get("where") or "",
        "country": filters.get("country") or "",
        "remote": filters.get("remote") or "",
        "source": filters.get("source") or "",
        "posted_within": filters.get("posted_within") or "",
        "has_salary": "1" if filters.get("has_salary") else "",
        "include_closed": "1" if filters.get("include_closed") else "",
        "sort": filters.get("sort") or "posted",
        "jk": chosen_jk or "",
    }
    if page_value != 1:
        pairs["page"] = page_value
    return urlencode({key: value for key, value in pairs.items() if value not in ("", None)})


def page_links(filters: dict[str, Any], pages: int) -> list[dict[str, Any]]:
    current = int(filters["page"])
    numbers = {1, pages, current}
    for number in range(current - 2, current + 3):
        if 1 <= number <= pages:
            numbers.add(number)
    links: list[dict[str, Any]] = []
    previous = 0
    for number in sorted(numbers):
        if previous and number - previous > 1:
            links.append({"ellipsis": True})
        links.append(
            {
                "n": number,
                "query": filter_query(filters, page=number),
                "current": number == current,
            }
        )
        previous = number
    return links


def _where(filters: dict[str, Any]) -> tuple[str, tuple[Any, ...]]:
    clauses = ["TRUE"]
    values: list[Any] = []
    if not filters["include_closed"]:
        clauses.append("j.closed_at IS NULL")
    if filters["q"]:
        clauses.append("j.search @@ websearch_to_tsquery('english', %s)")
        values.append(filters["q"])
    if filters["where"]:
        clauses.append("(j.city ILIKE %s OR j.country = upper(%s))")
        values.append(f"%{filters['where']}%")
        values.append(filters["where"])
    if filters["country"]:
        clauses.append("j.country = %s")
        values.append(str(filters["country"]).upper())
    if filters["posted_within"]:
        clauses.append("coalesce(j.posted_at, j.first_seen_at::date) >= current_date - %s::int")
        values.append(filters["posted_within"])
    if filters["has_salary"]:
        clauses.append("(j.salary_min IS NOT NULL OR j.salary_max IS NOT NULL)")
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
    row["place"] = ", ".join(str(part) for part in (row.get("city"), row.get("country")) if part)
    days = _age_days(row.get("posted_at"), row.get("first_seen_at"))
    row["age_days"] = days
    row["is_new"] = days is not None and days < 3
    row["age"] = "New" if row["is_new"] else _age_label(days)
    row["remote_label"] = _REMOTE_LABELS.get(str(row.get("remote") or ""), "Workplace unknown")
    sources = str(row.get("sources") or "")
    row["source_list"] = [part.strip() for part in sources.split(",") if part.strip()]
    snippet = str(row.get("snippet") or "")
    row["snippet"] = " ".join(snippet.split())
    row["stage"] = _stage(row)
    return row


def _stage(row: dict[str, Any]) -> str:
    if row.get("score") is not None:
        return "scored"
    if row.get("prefiltered") is None:
        return "not scored"
    if row.get("passed_hard") is False:
        return f"filtered out: {row.get('filter_reason')}"
    return "shortlisted" if row.get("shortlisted") else "not shortlisted"


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


def _age_days(posted: object, first_seen: object) -> int | None:
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
        return None
    return (date.today() - anchor).days


def _age_label(days: int | None) -> str:
    if days is None:
        return ""
    if days <= 0:
        return "Today"
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
