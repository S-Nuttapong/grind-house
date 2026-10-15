"""Re-run the composed parser on postings already stored. Does not call a model."""

from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from jobhunt.facts.apply import build_detail, record
from jobhunt.facts.base import JobDetail
from jobhunt.facts.coverage import coverage_table
from jobhunt.scrape.sources.base import RawPosting

_BATCH = 200


def run_reparse(conn: Connection[Any], *, source: str | None = None, dry_run: bool = False) -> str:
    before = coverage_table(conn)
    rows = _rows(conn, source)
    gained_pay: set[int] = set()
    gained_experience: set[int] = set()
    for index, row in enumerate(rows, start=1):
        detail, status = _parse(row)
        job_id = int(row["job_id"])
        if status == "done" and _missing_pay(row) and detail.pay is not None:
            gained_pay.add(job_id)
        if status == "done" and _missing_experience(row) and detail.experience is not None:
            gained_experience.add(job_id)
        if index % 500 == 0:
            print(f"reparse {index}/{len(rows)}", flush=True)
        if dry_run:
            continue
        record(conn, job_id, int(row["posting_id"]), detail, status)
        if index % _BATCH == 0:
            conn.commit()
    if dry_run:
        conn.rollback()
        after = f"{before}\n(dry run, not written)"
    else:
        conn.commit()
        after = coverage_table(conn)
    verb = "would gain" if dry_run else "gained"
    return "\n".join(
        (
            f"postings {len(rows)}",
            f"{verb} pay {len(gained_pay)}",
            f"{verb} experience {len(gained_experience)}",
            "",
            "before",
            before,
            "",
            "after",
            after,
            "",
        )
    )


def _rows(conn: Connection[Any], source: str | None) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT p.id AS posting_id, p.job_id, p.source_id, p.source_job_id, p.source_url,
                   c.name AS company_name, j.title, j.description_md, j.city, j.country,
                   j.remote, j.employment_type, j.posted_at, j.salary_min, j.salary_max,
                   j.experience_min_years, j.experience_max_years, rp.payload
            FROM postings p
            JOIN jobs j ON j.id = p.job_id
            JOIN companies c ON c.id = j.company_id
            LEFT JOIN LATERAL (
                SELECT payload FROM raw_payloads
                WHERE posting_id = p.id
                ORDER BY fetched_at DESC
                LIMIT 1
            ) rp ON true
            WHERE j.closed_at IS NULL
              AND (%s::text IS NULL OR p.source_id = %s)
            ORDER BY p.id
            """,
            (source, source),
        )
        return [dict(row) for row in cursor.fetchall()]


def _parse(row: dict[str, Any]) -> tuple[JobDetail, str]:
    payload = row["payload"] if isinstance(row["payload"], dict) else {}
    city = row["city"] if isinstance(row["city"], str) else ""
    country = str(row["country"] or "").strip()
    place = ", ".join(part for part in (city, country) if part)
    remote = row["remote"] if row["remote"] not in (None, "unknown") else None
    employment = row["employment_type"]
    description = row["description_md"] if isinstance(row["description_md"], str) else None
    posting = RawPosting(
        source_id=str(row["source_id"]),
        source_job_id=str(row["source_job_id"]),
        source_url=str(row["source_url"]),
        company_name=str(row["company_name"]),
        title=str(row["title"] or ""),
        location_raw=place or None,
        remote_hint=str(remote) if remote else None,
        employment_type_raw=employment if isinstance(employment, str) else None,
        posted_at=row["posted_at"],
        payload=payload,
    )
    return build_detail(posting, description)


def _missing_pay(row: dict[str, Any]) -> bool:
    return row["salary_min"] is None and row["salary_max"] is None


def _missing_experience(row: dict[str, Any]) -> bool:
    return row["experience_min_years"] is None and row["experience_max_years"] is None
