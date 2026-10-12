"""One pass over due searches and ATS scopes. launchd calls this every 15 minutes."""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from jobhunt import __version__
from jobhunt.composition import COMPOSITION
from jobhunt.core.db import advisory_lock, tx
from jobhunt.core.http import HttpClient, SourceBlocked
from jobhunt.core.log import get_logger
from jobhunt.fit.schedule import next_runs
from jobhunt.scrape import repo
from jobhunt.scrape.details import drain_details
from jobhunt.scrape.hooks import run_phase, vpn_state_path
from jobhunt.scrape.ingest import ingest_batch
from jobhunt.scrape.network import corporate_network
from jobhunt.scrape.pipeline import ScrapePipeline
from jobhunt.scrape.searches import expand
from jobhunt.scrape.sources.base import FetchContext, JobSource, RunPartial, ScopeView
from jobhunt.scrape.sources.pacing import Breaker

log = get_logger(__name__)

_WEEK = 7 * 24 * 3600
_MONTH = 30 * 24 * 3600
_CATCHUP_PAGES = {"linkedin_guest": 20, "seek": 5}
_BROWSER = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)


def adapter_for(source_id: str) -> JobSource:
    """Lookup used by the tick. Tests replace this."""
    return ScrapePipeline(COMPOSITION).source(source_id)


def tick(search_id: int | None = None) -> int:
    """Poll due markets. Returns 0 when another tick holds the lock or scraping is skipped."""
    with advisory_lock("jobhunt.tick") as acquired:
        if not acquired:
            log.info("another tick is running")
            return 0
        try:
            if vpn_state_path().exists():
                run_phase("after")
            before = run_phase("before_start")
            if before.skip:
                _skip("before_start hook failed")
                return 0
            if corporate_network():
                log.warning("corporate network detected, skipped")
                _skip("corporate network detected, skipped")
                return 0
            ran = _work(search_id)
            _maybe_close()
            return ran
        finally:
            run_phase("after")


def _work(search_id: int | None) -> int:
    with tx() as conn:
        plans = repo.load_search_work(conn, search_id)
        roles = set(repo.allowed_roles(conn))
        scopes = [] if search_id is not None else repo.due_scopes(conn)
        pending = repo.pending_sources(conn)
    grouped: dict[str, list[tuple[dict[str, Any], list[dict[str, Any]]]]] = defaultdict(list)
    for plan in plans:
        markets = _prepare_markets(plan)
        if markets:
            grouped[str(plan["source_id"])].append((plan, markets))
    scope_groups: dict[str, list[tuple[Any, ...]]] = defaultdict(list)
    for scope in scopes:
        scope_groups[str(scope[1])].append(scope)
    source_ids = sorted(set(grouped) | set(scope_groups) | set(pending))
    if not source_ids:
        return 0
    ran = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(
                _run_source,
                source_id,
                grouped.get(source_id, []),
                scope_groups.get(source_id, []),
                roles,
            )
            for source_id in source_ids
        ]
        for future in as_completed(futures):
            try:
                ran += future.result()
            except Exception:
                log.exception("source worker failed")
    return ran


def _prepare_markets(plan: dict[str, Any]) -> list[dict[str, Any]]:
    search_id = int(plan["search_id"])
    source_id = str(plan["source_id"])
    search = {
        "keywords": list(plan["keywords"]),
        "countries": [str(code).strip() for code in plan["countries"]],
        "sources": [source_id],
    }
    with tx() as conn:
        for _source, country, _params in expand(search):
            repo.ensure_market(conn, search_id, source_id, country)
        return repo.due_markets(conn, search_id, source_id, int(plan["poll_minutes"]))


def _run_source(
    source_id: str,
    jobs: list[tuple[dict[str, Any], list[dict[str, Any]]]],
    scopes: list[tuple[Any, ...]],
    roles: set[str],
) -> int:
    with advisory_lock(f"jobhunt.source.{source_id}") as acquired:
        if not acquired:
            log.info("source %s is already running", source_id)
            return 0
        http = _http(source_id)
        try:
            wide = False
            for plan, markets in jobs:
                if _poll(plan, markets, http, roles):
                    wide = True
            # A wide backfill already used this tick's request budget. Details wait
            # for a tick that only has incremental polls, or no search at all.
            if not wide:
                try:
                    drain_details(source_id, http)
                except (SourceBlocked, RunPartial) as exc:
                    log.warning("detail queue stopped: %s", exc)
            for scope in scopes:
                _run_ats(scope, http)
        finally:
            http._client.close()
    return 1


def _poll(
    plan: dict[str, Any],
    markets: list[dict[str, Any]],
    http: HttpClient,
    roles: set[str],
) -> bool:
    source_id = str(plan["source_id"])
    search_id = int(plan["search_id"])
    now = datetime.now(UTC)
    catchup = _catchup_due(now, str(plan["timezone"]), plan["last_catchup_at"])
    breaker = Breaker(prior=int(plan["strikes"] or 0))
    saved_cursor = plan["cursor"] if isinstance(plan["cursor"], dict) else {}
    adapter = adapter_for(source_id)
    params_for = {
        country: params
        for _source, country, params in expand(
            {
                "keywords": list(plan["keywords"]),
                "countries": [str(code).strip() for code in plan["countries"]],
                "sources": [source_id],
            }
        )
    }
    with tx() as conn:
        run_id = repo.start_run(
            conn,
            source_id=source_id,
            scraper_version=__version__,
            search_id=search_id,
        )
        known = set(repo.known_ids(conn, source_id))
    # A 7-day LinkedIn backfill is many pages. One market per tick stays under the
    # burst limit; the next tick continues with the next country.
    if source_id == "linkedin_guest" and (
        catchup or any(market["last_polled_at"] is None for market in markets)
    ):
        markets = markets[:1]
    fetched = new_jobs = updated = closed = skipped = 0
    status = "ok"
    error: str | None = None
    cursor: dict[str, Any] | None = None
    used_wide = False
    try:
        for market in markets:
            if breaker.opened:
                break
            country = str(market["country"])
            params = dict(params_for.get(country) or {})
            if not params:
                continue
            wide = _window(params, source_id, market["last_polled_at"], catchup, now, country)
            used_wide = wide or used_wide
            if wide and country == "TH":
                params["ignore_known"] = True
            if saved_cursor.get("market") == country:
                params["start_page"] = int(saved_cursor.get("page") or 0)
            params["known_ids"] = sorted(known)
            resume: int | None = None
            try:
                for batch in adapter.fetch(
                    ScopeView(id=0, source_id=source_id, params=params),
                    FetchContext(http=http, companies=[]),
                ):
                    with tx() as conn:
                        counts = ingest_batch(
                            conn,
                            run_id=run_id,
                            source_id=source_id,
                            batch=batch,
                            full_board=False,
                            allowed_roles=roles,
                        )
                    fetched += counts[0]
                    new_jobs += counts[1]
                    updated += counts[2]
                    closed += counts[3]
                    skipped += counts[4]
                    known.update(posting.source_job_id for posting in batch.postings)
                    if batch.resume_page is not None:
                        resume = batch.resume_page
            except SourceBlocked as exc:
                breaker.note_throttle()
                status = "partial"
                error = str(exc)
                page = resume if resume is not None else int(params.get("start_page") or 0)
                cursor = {"market": country, "page": page}
                _mark(search_id, source_id, country, "partial")
                continue
            except RunPartial as exc:
                status = "partial"
                error = str(exc)
                if "captcha" in str(exc).lower() or "login" in str(exc).lower():
                    breaker.note_throttle()
                _mark(search_id, source_id, country, "partial")
                continue
            if resume is None:
                _mark(search_id, source_id, country, "ok")
            else:
                cursor = {"market": country, "page": resume}
        if breaker.signals == 0:
            breaker.note_clean()
    except Exception as exc:
        status = "failed"
        error = str(exc)
        log.exception("search %s source %s failed", search_id, source_id)
    with tx() as conn:
        repo.finish_run(
            conn,
            run_id,
            status=status,
            fetched=fetched,
            new_jobs=new_jobs,
            updated=updated,
            closed=closed,
            skipped=skipped,
            error=error,
        )
        repo.save_breaker(
            conn,
            search_id,
            source_id,
            strikes=breaker.stored(),
            pause_minutes=breaker.pause_minutes if breaker.opened else 0,
            cursor=cursor,
            caught_up=catchup and not breaker.opened and status == "ok",
        )
    return used_wide


def _window(
    params: dict[str, Any],
    source_id: str,
    last_polled: datetime | None,
    catchup: bool,
    now: datetime,
    country: str,
) -> bool:
    # Thailand's 7-day software set is smaller than the acceptance count, so the
    # first pass there looks back 30 days. Other markets stay on the 7-day window.
    if last_polled is None and country == "TH" and source_id in {"linkedin_guest", "seek"}:
        seconds = _MONTH
        wide = True
    elif last_polled is None or catchup:
        seconds = _WEEK
        wide = True
    else:
        elapsed = int((now - last_polled).total_seconds()) + 15 * 60
        seconds = max(30 * 60, min(elapsed, _WEEK))
        wide = False
    if source_id == "linkedin_guest":
        params["f_tpr"] = seconds
        params["max_pages"] = _CATCHUP_PAGES["linkedin_guest"] if wide else 1
    elif source_id == "seek":
        params["date_range"] = 31 if seconds >= _MONTH else (7 if wide else 1)
        params["max_pages"] = _CATCHUP_PAGES["seek"] if wide else 1
    elif source_id in {"indeed", "glassdoor", "naukri"}:
        params["hours_old"] = max(1, min(168, (seconds + 3599) // 3600))
        params["results_wanted"] = 50
    return wide


def _run_ats(scope: tuple[Any, ...], http: HttpClient) -> None:
    scope_id = int(scope[0])
    try:
        ScrapePipeline(COMPOSITION).run(scope_id, str(scope[1]), http)
        upcoming = next_runs(str(scope[2]), str(scope[3]), 1)[0]
    except Exception:
        log.exception("scope %s failed", scope_id)
        upcoming = datetime.now(UTC) + timedelta(hours=6)
    with tx() as conn:
        repo.advance_scope(conn, scope_id, upcoming)


def _mark(search_id: int, source_id: str, country: str, status: str) -> None:
    with tx() as conn:
        repo.mark_market(conn, search_id, source_id, country, status)


def _maybe_close() -> None:
    if datetime.now(ZoneInfo("Asia/Bangkok")).hour < 3:
        return
    with tx() as conn:
        if repo.closed_today(conn):
            return
        closed = repo.close_stale_aggregators(conn)
        repo.insert_hook(
            conn,
            name="aggregator-close",
            phase="daily",
            exit_code=0,
            duration_ms=0,
        )
    log.info("closed %s stale aggregator jobs", closed)


def _skip(reason: str) -> None:
    with tx() as conn:
        plans = repo.load_search_work(conn, None)
        sources = sorted({str(plan["source_id"]) for plan in plans}) or ["linkedin_guest"]
        for source_id in sources:
            run_id = repo.start_run(conn, source_id=source_id, scraper_version=__version__)
            repo.finish_run(conn, run_id, status="skipped", error=reason)


def _catchup_due(now: datetime, timezone_name: str, last: datetime | None) -> bool:
    zone = ZoneInfo(timezone_name)
    local = now.astimezone(zone)
    if local.hour < 3:
        return False
    if last is None:
        return True
    return last.astimezone(zone).date() < local.date()


def _http(source_id: str) -> HttpClient:
    if source_id == "linkedin_guest":
        browser = httpx.Client(timeout=httpx.Timeout(30.0), headers={"User-Agent": _BROWSER})
        return HttpClient(browser, min_delay=6.0, max_delay=8.0)
    if source_id == "seek":
        browser = httpx.Client(
            timeout=httpx.Timeout(30.0),
            headers={"User-Agent": _BROWSER, "Accept": "application/json"},
            follow_redirects=True,
        )
        return HttpClient(browser, min_delay=2.0, max_delay=3.0)
    return HttpClient()
