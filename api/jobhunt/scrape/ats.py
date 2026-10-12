"""When a listing links to a company board, track that board directly."""

from typing import Any
from urllib.parse import urlparse

from psycopg import Connection
from psycopg.types.json import Jsonb

from jobhunt.core.log import get_logger

log = get_logger(__name__)

_ATS = (
    ("greenhouse.io", "greenhouse"),
    ("lever.co", "lever"),
    ("ashbyhq.com", "ashby"),
)
_UNSUPPORTED = ("workable.com", "smartrecruiters.com", "recruitee.com")


def detect_ats(url: str) -> tuple[str, str] | None:
    """Return ``(source_id, slug)`` for a Greenhouse, Lever, or Ashby apply link."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return None
    for suffix, source_id in _ATS:
        if host == suffix or host.endswith("." + suffix):
            return source_id, parts[0]
    return None


def unsupported_host(url: str) -> str | None:
    host = urlparse(url).netloc.lower()
    for suffix in _UNSUPPORTED:
        if host == suffix or host.endswith("." + suffix):
            return suffix
    return None


def follow_apply(conn: Connection[Any], company_id: int, url: str) -> str | None:
    """Set the company ATS when it has none, and add it to that board's scope.

    Returns an unsupported host so the tick can count boards we do not fetch yet.
    """
    found = detect_ats(url)
    if found is None:
        host = unsupported_host(url)
        if host is not None:
            log.info("unsupported ATS host %s for company %s", host, company_id)
        return host
    source_id, slug = found
    conn.execute(
        """
        UPDATE companies
        SET ats = %s, ats_slug = %s
        WHERE id = %s AND ats IS NULL
        """,
        (source_id, slug, company_id),
    )
    _add_company(conn, source_id, company_id)
    return None


def _add_company(conn: Connection[Any], source_id: str, company_id: int) -> None:
    name = f"Discovered {source_id}"
    row = conn.execute("SELECT id, params FROM fetch_scopes WHERE name = %s", (name,)).fetchone()
    if row is None:
        conn.execute(
            """
            INSERT INTO fetch_scopes (name, source_id, params, cron, timezone)
            VALUES (%s, %s, %s, '30 6 * * *', 'Asia/Bangkok')
            """,
            (name, source_id, Jsonb({"company_ids": [company_id]})),
        )
        return
    raw = row[1]
    params: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    stored = params.get("company_ids")
    ids = [int(item) for item in stored] if isinstance(stored, list) else []
    if company_id in ids:
        return
    ids.append(company_id)
    params["company_ids"] = ids
    conn.execute("UPDATE fetch_scopes SET params = %s WHERE id = %s", (Jsonb(params), row[0]))
