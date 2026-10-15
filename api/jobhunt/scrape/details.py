"""Fill descriptions for jobs the role filter kept. Cards are already on the board."""

from dataclasses import dataclass
from typing import Any

from jobhunt.core.db import advisory_lock, tx
from jobhunt.core.http import HttpClient, SourceBlocked
from jobhunt.core.log import get_logger
from jobhunt.scrape import repo
from jobhunt.scrape.ats import detect_ats, follow_apply
from jobhunt.scrape.network import corporate_network
from jobhunt.scrape.normalize.level import infer_level
from jobhunt.scrape.normalize.role import infer_industry
from jobhunt.scrape.normalize.text import html_to_md
from jobhunt.scrape.sources import linkedin, seek
from jobhunt.scrape.sources.base import RunPartial
from jobhunt.scrape.sources.linkedin import PostingGone

log = get_logger(__name__)

_LIMITS = {"linkedin_guest": 40, "seek": 60}
_THROTTLE_STREAK = 3


@dataclass
class DetailDrain:
    filled: int = 0
    gone: int = 0
    failed: int = 0
    deferred: int = 0
    stopped: str | None = None


@dataclass(frozen=True)
class BackfillResult:
    requeued: int
    filled: int
    gone: int
    pending: int


def drain_details(source_id: str, http: HttpClient, *, limit: int | None = None) -> DetailDrain:
    """Oldest pending postings first.

    A soft 429 leaves the posting pending and does not use an attempt. Three
    throttled postings in a row, or a hard block, stop the queue for this tick.
    """
    batch = _LIMITS.get(source_id) if limit is None else limit
    if batch is None:
        return DetailDrain()
    with tx() as conn:
        pending = repo.pending_details(conn, source_id, batch)
    outcome = DetailDrain()
    streak = 0
    for row in pending:
        posting_id = int(row["posting_id"])
        try:
            html, level_hint, industry_hint, apply_url = _fetch(source_id, http, row)
        except PostingGone:
            _gone(posting_id)
            outcome.gone += 1
            streak = 0
            continue
        except SourceBlocked as exc:
            if exc.status_code == 429:
                outcome.deferred += 1
                streak += 1
                if streak >= _THROTTLE_STREAK:
                    outcome.stopped = "throttled"
                    return outcome
                continue
            outcome.stopped = "blocked"
            return outcome
        except RunPartial:
            if source_id == "linkedin_guest":
                # A login wall is an IP block, not a bad posting.
                outcome.stopped = "blocked"
                return outcome
            _fail(posting_id)
            raise
        except Exception:
            log.exception("detail %s failed", posting_id)
            _fail(posting_id)
            outcome.failed += 1
            streak = 0
            continue
        if source_id == "linkedin_guest" and not html:
            _fail(posting_id)
            outcome.failed += 1
            streak = 0
            continue
        _save(row, html, level_hint, industry_hint, apply_url)
        outcome.filled += 1
        streak = 0
    return outcome


def backfill_details(source_id: str) -> BackfillResult:
    """Requeue open jobs with no description, then drain until empty or blocked."""
    if source_id not in _LIMITS:
        raise ValueError(f"{source_id} has no detail queue")
    if corporate_network():
        raise RuntimeError("corporate network detected, skipped")
    from jobhunt.scrape.tick import _http

    with advisory_lock(f"jobhunt.source.{source_id}") as acquired:
        if not acquired:
            raise RuntimeError(f"{source_id} is already running")
        with tx() as conn:
            requeued = repo.requeue_missing_details(conn, source_id)
        http = _http(source_id)
        filled = 0
        gone = 0
        try:
            while True:
                with tx() as conn:
                    waiting = repo.count_pending_details(conn, source_id)
                if waiting == 0:
                    break
                outcome = drain_details(source_id, http, limit=_LIMITS[source_id])
                filled += outcome.filled
                gone += outcome.gone
                if outcome.stopped:
                    log.warning("detail backfill stopped: %s", outcome.stopped)
                    break
        finally:
            http._client.close()
        with tx() as conn:
            pending = repo.count_pending_details(conn, source_id)
    return BackfillResult(requeued=requeued, filled=filled, gone=gone, pending=pending)


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
        _reparse(conn, int(row["posting_id"]), description)


def _reparse(conn: Any, posting_id: int, description: str | None) -> None:
    """Facts were parsed from the teaser. The full description can fill pay and experience."""
    loaded = repo.posting_for_parse(conn, posting_id)
    if loaded is None:
        return
    from jobhunt.facts.apply import build_detail, record
    from jobhunt.scrape.sources.base import RawPosting

    payload = loaded["payload"] if isinstance(loaded["payload"], dict) else {}
    city = loaded["city"] if isinstance(loaded["city"], str) else ""
    country = str(loaded["country"] or "").strip()
    place = ", ".join(part for part in (city, country) if part)
    remote = loaded["remote"] if loaded["remote"] not in (None, "unknown") else None
    employment = loaded["employment_type"]
    posting = RawPosting(
        source_id=str(loaded["source_id"]),
        source_job_id=str(loaded["source_job_id"]),
        source_url=str(loaded["source_url"]),
        company_name=str(loaded["company_name"]),
        title=str(loaded["title"] or ""),
        location_raw=place or None,
        remote_hint=str(remote) if remote else None,
        employment_type_raw=employment if isinstance(employment, str) else None,
        posted_at=loaded["posted_at"],
        payload=payload,
    )
    detail, status = build_detail(posting, description)
    record(conn, int(loaded["job_id"]), posting_id, detail, status)


def _fail(posting_id: int) -> None:
    with tx() as conn:
        repo.fail_detail(conn, posting_id)


def _gone(posting_id: int) -> None:
    with tx() as conn:
        repo.gone_detail(conn, posting_id)


def _text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value
