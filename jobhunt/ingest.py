"""Normalize a fetch batch, upsert jobs, and close postings that disappeared."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from psycopg import Connection

from jobhunt import __version__
from jobhunt.db import repo, tx
from jobhunt.http import HttpClient, SourceBlocked
from jobhunt.log import get_logger, redact
from jobhunt.normalize.company import norm_company
from jobhunt.normalize.level import infer_level
from jobhunt.normalize.location import parse_location
from jobhunt.normalize.salary import normalize_salary
from jobhunt.normalize.text import content_hash, html_to_md
from jobhunt.normalize.title import norm_title
from jobhunt.settings import load_settings
from jobhunt.sources.base import (
    CompanyTarget,
    FetchBatch,
    FetchContext,
    RawPosting,
    ScopeView,
    SourceAdapter,
)

log = get_logger(__name__)

_ATS = "ats"


@dataclass
class RunResult:
    run_id: int
    status: str
    fetched: int = 0
    new_jobs: int = 0
    updated: int = 0
    closed: int = 0
    error: str | None = None


@dataclass
class _Normalized:
    title_norm: str
    level: str
    country: str | None
    city: str | None
    remote: str
    tz_min: int | None
    tz_max: int | None
    employment_type: str | None
    salary_min: Decimal | None
    salary_max: Decimal | None
    salary_currency: str | None
    salary_interval: str | None
    salary_usd_year_min: Decimal | None
    description_md: str | None
    digest: str
    apply_url: str


def run_scope(scope_id: int, adapter: SourceAdapter, http: HttpClient | None = None) -> RunResult:
    """Fetch one scope and ingest each company batch in its own transaction."""
    with tx() as conn:
        scope_row = repo.get_scope(conn, scope_id)
        if scope_row is None:
            raise ValueError(f"fetch scope {scope_id} does not exist")
        run_id = repo.start_run(
            conn,
            source_id=str(scope_row[2]),
            scraper_version=__version__,
            scope_id=scope_id,
        )
        companies = [
            CompanyTarget(id=int(row[0]), name=str(row[1]), ats_slug=str(row[2]), tier=row[3])
            for row in repo.list_ats_companies(conn, adapter.id)
        ]
        params = scope_row[3] if isinstance(scope_row[3], dict) else {}
        scope = ScopeView(id=int(scope_row[0]), source_id=str(scope_row[2]), params=params)
    ctx = FetchContext(http=http or HttpClient(), companies=companies)
    result = RunResult(run_id=run_id, status="ok")
    try:
        for batch in adapter.fetch(scope, ctx):
            with tx() as conn:
                counts = ingest_batch(
                    conn,
                    run_id=run_id,
                    source_id=adapter.id,
                    batch=batch,
                    full_board=adapter.full_board,
                )
            result.fetched += counts[0]
            result.new_jobs += counts[1]
            result.updated += counts[2]
            result.closed += counts[3]
            if batch.failed:
                result.status = "partial"
    except SourceBlocked as exc:
        result.status = "partial"
        result.error = str(exc)
        log.warning("%s", exc)
    except Exception as exc:
        result.status = "failed"
        result.error = redact(str(exc))
        log.exception("scope %s failed", scope_id)
    with tx() as conn:
        repo.finish_run(
            conn,
            run_id,
            status=result.status,
            fetched=result.fetched,
            new_jobs=result.new_jobs,
            updated=result.updated,
            closed=result.closed,
            error=result.error,
        )
    return result


def ingest_batch(
    conn: Connection[Any],
    *,
    run_id: int,
    source_id: str,
    batch: FetchBatch,
    full_board: bool,
    similarity: float | None = None,
) -> tuple[int, int, int, int]:
    """Upsert one company batch. Returns fetched, new_jobs, updated, closed."""
    if batch.failed:
        if batch.clear_ats and batch.company_id is not None:
            repo.clear_company_ats(conn, batch.company_id)
            log.info("cleared ATS for company %s after HTTP 404", batch.company_id)
        return (0, 0, 0, 0)
    threshold = load_settings().title_similarity if similarity is None else similarity
    fetched = new_jobs = updated = 0
    for posting in batch.postings:
        outcome = _upsert(
            conn,
            run_id=run_id,
            posting=posting,
            company_id=batch.company_id,
            similarity=threshold,
        )
        fetched += 1
        if outcome == "new":
            new_jobs += 1
        elif outcome == "updated":
            updated += 1
    closed = 0
    if full_board and batch.company_id is not None:
        closed = repo.close_missing(conn, batch.company_id, source_id, run_id)
    return fetched, new_jobs, updated, closed


def _upsert(
    conn: Connection[Any],
    *,
    run_id: int,
    posting: RawPosting,
    company_id: int | None,
    similarity: float,
) -> str:
    normalized = _normalize(posting)
    existing = repo.get_posting(conn, posting.source_id, posting.source_job_id)
    if existing is not None:
        posting_id = int(existing[0])
        job_id = int(existing[1])
        previous_hash = str(existing[5])
        repo.touch_posting(
            conn,
            posting_id,
            run_id=run_id,
            content_hash=normalized.digest,
            source_url=posting.source_url,
        )
        repo.touch_job(conn, job_id)
        if previous_hash == normalized.digest:
            return "seen"
        _write_job(conn, job_id, posting, normalized, company_id or _company_id(conn, job_id))
        repo.insert_raw_payload(conn, posting_id=posting_id, run_id=run_id, payload=posting.payload)
        return "updated"

    resolved = company_id if company_id is not None else _resolve_company(conn, posting)
    dedupe_key = f"{resolved}|{normalized.title_norm}|{normalized.country or '??'}"
    duplicate = repo.find_open_duplicate(
        conn,
        company_id=resolved,
        title_norm=normalized.title_norm,
        country=normalized.country,
        dedupe_key=dedupe_key,
        threshold=similarity,
    )
    if duplicate is None:
        job_id = _insert_job(conn, resolved, posting, normalized, dedupe_key)
        outcome = "new"
    else:
        job_id = duplicate
        repo.fill_job_gaps(
            conn,
            job_id,
            salary_min=normalized.salary_min,
            salary_max=normalized.salary_max,
            salary_currency=normalized.salary_currency,
            salary_interval=normalized.salary_interval,
            salary_usd_year_min=normalized.salary_usd_year_min,
            posted_at=posting.posted_at,
            remote=normalized.remote,
            tz_min=normalized.tz_min,
            tz_max=normalized.tz_max,
        )
        if repo.source_kind(conn, posting.source_id) == _ATS and not repo.job_has_ats_posting(
            conn, job_id
        ):
            repo.set_apply_url(conn, job_id, normalized.apply_url)
        outcome = "attached"
    posting_id = repo.insert_posting(
        conn,
        job_id=job_id,
        source_id=posting.source_id,
        source_job_id=posting.source_job_id,
        source_url=posting.source_url,
        content_hash=normalized.digest,
        run_id=run_id,
    )
    repo.insert_raw_payload(conn, posting_id=posting_id, run_id=run_id, payload=posting.payload)
    return outcome


def _company_id(conn: Connection[Any], job_id: int) -> int:
    row = conn.execute("SELECT company_id FROM jobs WHERE id = %s", (job_id,)).fetchone()
    if row is None:
        raise RuntimeError(f"job {job_id} disappeared during ingest")
    return int(row[0])


def _resolve_company(conn: Connection[Any], posting: RawPosting) -> int:
    hint = posting.company_hint
    ats = hint.get("ats")
    slug = hint.get("slug")
    if isinstance(ats, str) and isinstance(slug, str):
        found = repo.get_company_by_ats(conn, ats, slug)
        if found is not None:
            return int(found[0])
    name_norm = norm_company(posting.company_name)
    alias = repo.get_alias_company_id(conn, name_norm)
    if alias is not None:
        return alias
    existing = repo.get_company_by_name_norm(conn, name_norm)
    if existing is not None:
        return int(existing[0])
    return repo.insert_company(conn, name=posting.company_name, name_norm=name_norm)


def _normalize(posting: RawPosting) -> _Normalized:
    title_norm = norm_title(posting.title)
    country, city, remote, tz_min, tz_max = parse_location(
        posting.location_raw, posting.remote_hint
    )
    low, high, currency, interval, usd = normalize_salary(
        posting.salary_min,
        posting.salary_max,
        posting.salary_currency,
        posting.salary_interval_raw,
    )
    description: str | None
    if posting.description_html:
        description = html_to_md(posting.description_html)
    else:
        description = (posting.description_text or "").strip() or None
    return _Normalized(
        title_norm=title_norm,
        level=infer_level(posting.title, posting.level_hint),
        country=country,
        city=city,
        remote=remote,
        tz_min=tz_min,
        tz_max=tz_max,
        employment_type=_employment(posting.employment_type_raw),
        salary_min=low,
        salary_max=high,
        salary_currency=currency,
        salary_interval=interval,
        salary_usd_year_min=usd,
        description_md=description,
        digest=content_hash(title_norm, description),
        apply_url=posting.apply_url or posting.source_url,
    )


def _insert_job(
    conn: Connection[Any],
    company_id: int,
    posting: RawPosting,
    normalized: _Normalized,
    dedupe_key: str,
) -> int:
    return repo.insert_job(
        conn,
        company_id=company_id,
        title=posting.title,
        title_norm=normalized.title_norm,
        apply_url=normalized.apply_url,
        dedupe_key=dedupe_key,
        level=normalized.level,
        country=normalized.country,
        city=normalized.city,
        remote=normalized.remote,
        tz_min=normalized.tz_min,
        tz_max=normalized.tz_max,
        employment_type=normalized.employment_type,
        salary_min=normalized.salary_min,
        salary_max=normalized.salary_max,
        salary_currency=normalized.salary_currency,
        salary_interval=normalized.salary_interval,
        salary_usd_year_min=normalized.salary_usd_year_min,
        posted_at=posting.posted_at,
        description_md=normalized.description_md,
    )


def _write_job(
    conn: Connection[Any],
    job_id: int,
    posting: RawPosting,
    normalized: _Normalized,
    company_id: int,
) -> None:
    dedupe_key = f"{company_id}|{normalized.title_norm}|{normalized.country or '??'}"
    repo.update_job_content(
        conn,
        job_id,
        title=posting.title,
        title_norm=normalized.title_norm,
        level=normalized.level,
        country=normalized.country,
        city=normalized.city,
        remote=normalized.remote,
        tz_min=normalized.tz_min,
        tz_max=normalized.tz_max,
        employment_type=normalized.employment_type,
        salary_min=normalized.salary_min,
        salary_max=normalized.salary_max,
        salary_currency=normalized.salary_currency,
        salary_interval=normalized.salary_interval,
        salary_usd_year_min=normalized.salary_usd_year_min,
        posted_at=posting.posted_at,
        description_md=normalized.description_md,
        dedupe_key=dedupe_key,
        apply_url=normalized.apply_url,
    )


def _employment(raw: str | None) -> str | None:
    if not raw:
        return None
    text = raw.lower().replace("_", "").replace("-", "").replace(" ", "")
    if "intern" in text:
        return "internship"
    if "part" in text:
        return "parttime"
    if "contract" in text or "temp" in text:
        return "contract"
    if "full" in text or "permanent" in text:
        return "fulltime"
    return None
