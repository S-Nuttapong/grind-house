"""Board queries. Sort columns come from a fixed whitelist."""

import re
from datetime import date, datetime
from functools import cache
from typing import Any

import pycountry
from psycopg import Connection
from psycopg.rows import dict_row

from jobhunt.jobs.geo import countries_for, region_ids
from jobhunt.scrape.normalize.role import industry_ids, role_ids

PAGE_SIZE = 40
_PAY_JOIN = "LEFT JOIN job_base_pay bp ON bp.job_id = j.id"
_PAY_COLUMNS = (
    "bp.min_amount AS salary_min, bp.max_amount AS salary_max, bp.currency AS salary_currency"
)
# Same date the card shows as age. The query is a filter, never a sort key.
_RECENCY = "coalesce(j.posted_at, j.first_seen_at::date)"
_NEWEST = f"{_RECENCY} DESC, j.id DESC"
_SORTS = {
    "newest": _NEWEST,
    "oldest": f"{_RECENCY} ASC NULLS LAST, j.id ASC",
    "fit_desc": f"fit.score DESC NULLS LAST, {_NEWEST}",
    "fit_asc": f"fit.score ASC NULLS LAST, {_NEWEST}",
}
_SORT_ALIASES = {
    "match": "fit_desc",
    "posted": "newest",
    "first_seen": "newest",
}
_FIT_MODES = {"bank", "resume"}
_POSTED_WITHIN = {1, 3, 7, 14, 30}
_STATUSES = {"saved", "skipped", "applied", "removed"}
_LABELS = {"saved": "maybe", "skipped": "skip", "applied": "apply"}
_REMOTE_LABELS = {
    "remote": "Remote",
    "hybrid": "Hybrid",
    "onsite": "On-site",
    "unknown": "Workplace unknown",
}
PIPELINE_STATUSES = ("saved", "applied", "skipped")
_LEVELS = (
    "intern",
    "junior",
    "mid",
    "senior",
    "staff",
    "principal",
    "lead",
    "manager",
    "unknown",
)
_SOURCE_ID = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
_SCORE_COLUMNS = """fit.score, fit.matched_terms, fit.missing_terms, fit.source_hash AS fit_source,
            fit.model_id AS fit_model_id, fit.coverage, fit.gaps"""
# The latest row for the live scorer and a finished source. Other models stay hidden.
_SCORE_JOINS = """
            LEFT JOIN LATERAL (
              SELECT jf.score, jf.matched_terms, jf.missing_terms, jf.source_hash,
                     jf.model_id, jf.coverage, jf.gaps
              FROM job_fits jf
              JOIN fit_sources fs ON fs.hash = jf.source_hash
              WHERE jf.job_id = j.id AND fs.kind = %s AND jf.model_id = %s
                AND fs.scored_at IS NOT NULL
              ORDER BY jf.computed_at DESC, fs.scored_at DESC
              LIMIT 1
            ) fit ON TRUE"""


def _fit_model_id() -> str:
    from jobhunt.composition import COMPOSITION

    return COMPOSITION.scorer.model_id


def parse_filters(params: dict[str, str]) -> dict[str, Any]:
    raw_sort = params.get("sort") or "newest"
    sort = _SORT_ALIASES.get(raw_sort, raw_sort)
    if sort not in _SORTS:
        sort = "newest"
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
        "country": _list(params.get("country"), _iso_countries(), upper=True),
        "region": _list(params.get("region"), set(region_ids())),
        "role": _list(params.get("role"), role_ids()),
        "industry": _list(params.get("industry"), industry_ids()),
        "remote": _list(params.get("remote"), set(_REMOTE_LABELS)),
        "source": _list(params.get("source"), None),
        "level": _list(params.get("level"), set(_LEVELS)),
        "posted_within": posted_within,
        "has_salary": params.get("has_salary") == "1",
        "min_experience": _min_experience(params.get("min_experience")),
        "include_closed": params.get("include_closed") == "1",
        "jk": int(jk_raw) if jk_raw and jk_raw.isdigit() else None,
        "fit": params.get("fit") if params.get("fit") in _FIT_MODES else "bank",
        "min_score": _min_score(params.get("min_score")),
        "sort": sort,
        "page": page,
    }


def list_jobs(conn: Connection[Any], filters: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    where, values = _where(filters)
    order = _SORTS[str(filters["sort"])]
    offset = (int(filters["page"]) - 1) * PAGE_SIZE
    fit_mode = filters["fit"]
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"""
            SELECT count(*) AS n FROM jobs j
            JOIN companies c ON c.id = j.company_id
            {_PAY_JOIN}
            {_SCORE_JOINS}
            {where}
            """,
            (fit_mode, _fit_model_id(), *values),
        )
        total_row = cursor.fetchone()
        total = int(total_row["n"]) if total_row else 0
        cursor.execute(
            f"""
            SELECT j.id, j.title, c.name AS company, j.city, j.country, j.remote,
                   j.employment_type, {_PAY_COLUMNS},
                   j.experience_min_years, j.experience_max_years,
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
            {_PAY_JOIN}
            LEFT JOIN job_status s ON s.job_id = j.id
            {_SCORE_JOINS}
            {where}
            ORDER BY {order}
            LIMIT %s OFFSET %s
            """,
            (fit_mode, _fit_model_id(), *values, PAGE_SIZE, offset),
        )
        rows = [_present(dict(row)) for row in cursor.fetchall()]
    return rows, total


def get_job(conn: Connection[Any], job_id: int, fit_mode: str = "bank") -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"""
            SELECT j.id, j.title, c.name AS company, j.city, j.country, j.remote,
                   j.employment_type, {_PAY_COLUMNS},
                   j.experience_min_years, j.experience_max_years,
                   j.posted_at, j.first_seen_at, j.closed_at, j.apply_url, j.description_md,
                   s.status, {_SCORE_COLUMNS},
                   (
                     SELECT string_agg(DISTINCT p.source_id, ', ' ORDER BY p.source_id)
                     FROM postings p WHERE p.job_id = j.id
                   ) AS sources
            FROM jobs j
            JOIN companies c ON c.id = j.company_id
            {_PAY_JOIN}
            LEFT JOIN job_status s ON s.job_id = j.id
            {_SCORE_JOINS}
            WHERE j.id = %s
            """,
            (fit_mode, _fit_model_id(), job_id),
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
    job["coverage"] = None if job.get("coverage") is None else float(job["coverage"])
    job["gaps"] = [str(item) for item in job.get("gaps") or []]
    job["top_brags"] = []
    if job.get("fit_model_id") and job.get("fit_source"):
        from jobhunt.fit import repo as fit_repo

        job["top_brags"] = fit_repo.matches_for(
            conn, job_id, str(job["fit_model_id"]), str(job["fit_source"])
        )
    return job


def list_pipeline(conn: Connection[Any]) -> dict[str, list[dict[str, Any]]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"""
            SELECT j.id, j.title, c.name AS company, j.city, j.country, j.remote,
                   j.employment_type, {_PAY_COLUMNS},
                   j.experience_min_years, j.experience_max_years,
                   j.posted_at, j.first_seen_at, j.closed_at, j.apply_url,
                   s.status, s.at AS status_at, {_SCORE_COLUMNS},
                   '' AS snippet,
                   (
                     SELECT string_agg(DISTINCT p.source_id, ', ' ORDER BY p.source_id)
                     FROM postings p WHERE p.job_id = j.id
                   ) AS sources,
                   (
                     SELECT rr.status FROM resume_runs rr
                     WHERE rr.job_id = j.id
                     ORDER BY rr.created_at DESC, rr.id DESC
                     LIMIT 1
                   ) AS resume_status
            FROM job_status s
            JOIN jobs j ON j.id = s.job_id
            JOIN companies c ON c.id = j.company_id
            {_PAY_JOIN}
            LEFT JOIN pipeline_ranks pr ON pr.job_id = j.id
            {_SCORE_JOINS}
            WHERE s.status = ANY(%s)
            ORDER BY pr.rank ASC NULLS FIRST, s.at DESC
            LIMIT 300
            """,
            ("bank", _fit_model_id(), list(PIPELINE_STATUSES)),
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
        cursor.execute(
            """
            SELECT DISTINCT country FROM jobs
            WHERE closed_at IS NULL AND country IS NOT NULL
            ORDER BY country
            """
        )
        countries = [str(row[0]).strip() for row in cursor.fetchall() if str(row[0]).strip()]
        cursor.execute(
            """
            SELECT DISTINCT role FROM jobs
            WHERE closed_at IS NULL AND role IS NOT NULL
            ORDER BY role
            """
        )
        roles = [str(row[0]) for row in cursor.fetchall()]
        cursor.execute(
            """
            SELECT DISTINCT industry FROM jobs
            WHERE closed_at IS NULL AND industry IS NOT NULL
            ORDER BY industry
            """
        )
        industries = [str(row[0]) for row in cursor.fetchall()]
    return {
        "sources": sources,
        "remote": list(_REMOTE_LABELS),
        "countries": countries,
        "regions": region_ids(),
        "roles": roles,
        "industries": industries,
        "levels": list(_LEVELS),
    }


def arrange_pipeline(conn: Connection[Any], columns: dict[str, list[int]]) -> None:
    """Put each column in the given order, and move a job when its column changed."""
    ordered: list[int] = []
    for status in PIPELINE_STATUSES:
        for job_id in columns.get(status, []):
            if job_id not in ordered:
                ordered.append(job_id)
    if not ordered:
        return
    found = {
        int(row[0])
        for row in conn.execute("SELECT id FROM jobs WHERE id = ANY(%s)", (ordered,)).fetchall()
    }
    current = {
        int(row[0]): str(row[1])
        for row in conn.execute(
            "SELECT job_id, status FROM job_status WHERE job_id = ANY(%s)",
            (ordered,),
        ).fetchall()
    }
    for status in PIPELINE_STATUSES:
        ranked: list[int] = []
        for job_id in columns.get(status, []):
            if job_id not in found or job_id in ranked:
                continue
            ranked.append(job_id)
            if current.get(job_id) != status:
                record_event(conn, job_id, status, None)
        _set_ranks(conn, ranked)


def _set_ranks(conn: Connection[Any], job_ids: list[int]) -> None:
    for index, job_id in enumerate(job_ids):
        conn.execute(
            """
            INSERT INTO pipeline_ranks (job_id, rank) VALUES (%s, %s)
            ON CONFLICT (job_id) DO UPDATE SET rank = EXCLUDED.rank
            """,
            (job_id, index),
        )


def record_events(
    conn: Connection[Any], job_ids: list[int], status: str, reason: str | None
) -> list[int]:
    """Record one status for each job that exists. Unknown ids are skipped."""
    rows = conn.execute("SELECT id FROM jobs WHERE id = ANY(%s)", (job_ids,)).fetchall()
    found = {int(row[0]) for row in rows}
    updated: list[int] = []
    for job_id in job_ids:
        if job_id not in found or job_id in updated:
            continue
        record_event(conn, job_id, status, reason)
        updated.append(job_id)
    return updated


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
    conn.execute("DELETE FROM pipeline_ranks WHERE job_id = %s", (job_id,))
    if status == "removed":
        conn.execute(
            "DELETE FROM labels WHERE job_id = %s AND origin = 'ui_action'",
            (job_id,),
        )
        return
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
    countries = set(filters["country"])
    for region in filters["region"]:
        countries.update(countries_for(region))
    if countries:
        clauses.append("j.country = ANY(%s)")
        values.append(sorted(countries))
    if filters["posted_within"]:
        clauses.append("coalesce(j.posted_at, j.first_seen_at::date) >= current_date - %s::int")
        values.append(filters["posted_within"])
    if filters["has_salary"]:
        clauses.append("bp.job_id IS NOT NULL")
    if filters.get("min_experience"):
        clauses.append("j.experience_min_years >= %s")
        values.append(filters["min_experience"])
    for column, key in (
        ("j.remote", "remote"),
        ("j.role", "role"),
        ("j.industry", "industry"),
        ("j.level", "level"),
    ):
        selected = filters[key]
        if selected:
            clauses.append(f"{column} = ANY(%s)")
            values.append(selected)
    if filters["source"]:
        clauses.append(
            "EXISTS (SELECT 1 FROM postings p WHERE p.job_id = j.id AND p.source_id = ANY(%s))"
        )
        values.append(filters["source"])
    if filters.get("min_score") is not None:
        clauses.append("fit.score >= %s")
        values.append(filters["min_score"])
    return "WHERE " + " AND ".join(clauses), tuple(values)


def _list(raw: str | None, allowed: set[str] | None, *, upper: bool = False) -> list[str]:
    """Split a comma list, drop blanks and values outside the allowlist."""
    if not raw:
        return []
    chosen: list[str] = []
    for part in raw.split(","):
        value = part.strip()
        if not value:
            continue
        value = value.upper() if upper else value.lower()
        if allowed is None:
            if not _SOURCE_ID.fullmatch(value):
                continue
        elif value not in allowed:
            continue
        if value not in chosen:
            chosen.append(value)
    return chosen


@cache
def _iso_countries() -> set[str]:
    return {str(country.alpha_2) for country in pycountry.countries}


def _min_experience(raw: str | None) -> int:
    if raw and raw.isdigit():
        value = int(raw)
        if 0 <= value <= 15:
            return value
    return 0


def _min_score(raw: str | None) -> int | None:
    if raw and raw.isdigit():
        value = int(raw)
        if 0 <= value <= 100:
            return value
    return None


def _present(row: dict[str, Any]) -> dict[str, Any]:
    row["salary_label"] = _salary(row)
    row["experience_label"] = _experience_label(row)
    row["place"] = ", ".join(str(part) for part in (row.get("city"), row.get("country")) if part)
    days = _age_days(row.get("posted_at"), row.get("first_seen_at"))
    row["age_days"] = days
    row["is_new"] = days is not None and days < 3
    row["age"] = _age_label(days)
    row["remote_label"] = _REMOTE_LABELS.get(str(row.get("remote") or ""), "Workplace unknown")
    sources = str(row.get("sources") or "")
    row["source_list"] = [part.strip() for part in sources.split(",") if part.strip()]
    snippet = str(row.get("snippet") or "")
    row["snippet"] = " ".join(snippet.split())
    row["stage"] = _stage(row)
    row["fit_tier"] = _tier(row.get("score"))
    row["matched_terms"] = list(row.get("matched_terms") or [])
    row["missing_terms"] = list(row.get("missing_terms") or [])
    return row


def _tier(score: Any) -> str | None:
    if score is None:
        return None
    value = float(score)
    if value >= 80:
        return "strong"
    if value >= 60:
        return "good"
    if value >= 40:
        return "fair"
    return "low"


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
    if low is not None and high is not None and _as_int(low) == _as_int(high):
        amount = f"{_as_int(low):,}"
    elif low is not None and high is not None:
        amount = f"{_as_int(low):,}–{_as_int(high):,}"
    elif low is not None:
        amount = f"{_as_int(low):,}+"
    elif high is not None:
        amount = f"up to {_as_int(high):,}"
    else:
        return None
    return f"{amount} {currency}".strip()


def _experience_label(row: dict[str, Any]) -> str | None:
    low = row.get("experience_min_years")
    high = row.get("experience_max_years")
    minimum = low if isinstance(low, int) else None
    maximum = high if isinstance(high, int) else None
    if minimum is None and maximum is None:
        return None
    if minimum is not None and maximum is not None and minimum != maximum:
        return f"{minimum}-{maximum} yrs"
    if minimum is not None:
        return f"{minimum}+ yrs" if maximum is None else f"{minimum} yrs"
    if maximum is None:
        return None
    return f"up to {maximum} yrs"


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
    return f"{max(days, 0)}d"


def _blank(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return int(str(value))
    return int(value)
