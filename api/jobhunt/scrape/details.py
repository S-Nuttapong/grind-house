"""Fill descriptions for jobs the role filter kept. Cards are already on the board."""

from typing import Any

from jobhunt.core.db import tx
from jobhunt.core.http import HttpClient, SourceBlocked
from jobhunt.core.log import get_logger
from jobhunt.scrape import repo
from jobhunt.scrape.ats import detect_ats, follow_apply
from jobhunt.scrape.normalize.level import infer_level
from jobhunt.scrape.normalize.role import infer_industry
from jobhunt.scrape.normalize.text import html_to_md
from jobhunt.scrape.sources import linkedin, seek
from jobhunt.scrape.sources.base import RunPartial

log = get_logger(__name__)

_LIMITS = {"linkedin_guest": 40, "seek": 60}


def drain_details(source_id: str, http: HttpClient) -> None:
    """Oldest pending postings first. A block stops the queue for this tick."""
    limit = _LIMITS.get(source_id)
    if limit is None:
        return
    with tx() as conn:
        pending = repo.pending_details(conn, source_id, limit)
    for row in pending:
        posting_id = int(row["posting_id"])
        try:
            html, level_hint, industry_hint, apply_url = _fetch(source_id, http, row)
        except SourceBlocked:
            raise
        except RunPartial:
            _fail(posting_id)
            raise
        except Exception:
            log.exception("detail %s failed", posting_id)
            _fail(posting_id)
            continue
        _save(row, html, level_hint, industry_hint, apply_url)


def _fetch(
    source_id: str, http: HttpClient, row: dict[str, Any]
) -> tuple[str | None, str | None, str | None, str | None]:
    job_id = str(row["source_job_id"])
    if source_id == "linkedin_guest":
        detail = linkedin.fetch_detail(http, job_id)
        return (
            _text(detail.get("description_html")),
            _text(detail.get("level_hint")),
            _text(detail.get("industry_hint")),
            _text(detail.get("apply_url")),
        )
    with tx() as conn:
        host = repo.posting_host(conn, int(row["posting_id"]))
    if not host:
        raise RunPartial(source_id, "posting has no SEEK host")
    return seek.fetch_detail(http, host, job_id), None, None, None


def _save(
    row: dict[str, Any],
    html: str | None,
    level_hint: str | None,
    industry_hint: str | None,
    apply_url: str | None,
) -> None:
    title = str(row["title"])
    level = infer_level(title, level_hint) if level_hint else None
    industry = infer_industry(industry_hint) if industry_hint else None
    description = html_to_md(html) if html else None
    offsite = apply_url if apply_url and detect_ats(apply_url) else None
    with tx() as conn:
        repo.finish_detail(
            conn,
            posting_id=int(row["posting_id"]),
            job_id=int(row["job_id"]),
            description_md=description,
            level=level,
            industry=industry,
            apply_url=offsite,
        )
        if offsite:
            follow_apply(conn, int(row["company_id"]), offsite)


def _fail(posting_id: int) -> None:
    with tx() as conn:
        repo.fail_detail(conn, posting_id)


def _text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value
