"""Recompute role and industry for jobs already in the database."""

from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from jobhunt.core.db import tx
from jobhunt.scrape.normalize.role import infer_industry, infer_role
from jobhunt.scrape.sources.parse import as_dict


def backfill_roles() -> int:
    with tx() as conn:
        return apply_backfill(conn)


def apply_backfill(conn: Connection[Any]) -> int:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT j.id, j.title, c.name AS company, payload.payload
            FROM jobs j
            JOIN companies c ON c.id = j.company_id
            LEFT JOIN LATERAL (
              SELECT rp.payload
              FROM postings p
              JOIN raw_payloads rp ON rp.posting_id = p.id
              WHERE p.job_id = j.id
              ORDER BY rp.fetched_at DESC
              LIMIT 1
            ) payload ON TRUE
            """
        )
        rows = cursor.fetchall()
    updated = 0
    for row in rows:
        payload = as_dict(row.get("payload"))
        role_hint, industry_hint = _hints(payload)
        role = infer_role(str(row["title"]), role_hint)
        industry = infer_industry(industry_hint, str(row["company"]))
        conn.execute(
            "UPDATE jobs SET role = %s, industry = %s WHERE id = %s",
            (role, industry, int(row["id"])),
        )
        updated += 1
    return updated


def _hints(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    role = _text(payload.get("job_function"))
    industry = _text(payload.get("company_industry"))
    category = as_dict(payload.get("category"))
    label = _text(category.get("label"))
    categories = payload.get("categories")
    if isinstance(categories, list):
        for item in categories:
            found = _text(as_dict(item).get("category"))
            if found:
                label = label or found
                break
    return role or label, industry or label


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
