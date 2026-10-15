"""LinkedIn guest search. No login. Cards first; descriptions come from the detail queue."""

import re
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from bs4 import BeautifulSoup
from tenacity import RetryError

from jobhunt.core.http import HttpClient, SourceBlocked
from jobhunt.facts.base import JobDetail
from jobhunt.scrape.sources.base import (
    FetchBatch,
    FetchContext,
    RawPosting,
    RunPartial,
    ScopeView,
    SourceDefaults,
    SourceSpec,
)
from jobhunt.scrape.sources.jobspy_src import jobspy_facts
from jobhunt.scrape.sources.pacing import empty_is_throttle

_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
_DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
_BROWSER = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
_ATS = re.compile(
    r"https://[^\"'\s>]*(?:greenhouse\.io|lever\.co|ashbyhq\.com|"
    r"workable\.com|smartrecruiters\.com|recruitee\.com)[^\"'\s>]*",
    re.IGNORECASE,
)
_MAX_PAGES = 20
# A 429 on the detail endpoint clears in about 2.5s. The later waits are a margin.
_RETRY_AFTER = (2.5, 5.0, 10.0, 20.0)


class PostingGone(Exception):
    """LinkedIn returned 404: the posting was taken down."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"linkedin job {job_id} is no longer posted")
        self.job_id = job_id


class LinkedInSource(SourceDefaults):
    id = "linkedin_guest"
    kind = "aggregator"
    full_board = False
    needs_detail_fetch = True
    spec = SourceSpec(
        kind="aggregator",
        min_interval=timedelta(minutes=15),
        close_after=timedelta(days=14),
    )

    def payload_facts(self, payload: dict[str, Any]) -> JobDetail:
        return jobspy_facts(self.id, payload)

    def fetch(self, scope: ScopeView, ctx: FetchContext) -> Iterator[FetchBatch]:
        params = scope.params
        geo_id = str(params.get("geo_id") or "")
        query = str(params.get("search_term") or "")
        if not geo_id or not query:
            raise RunPartial(self.id, "geo_id and search_term are required")
        http = _client(ctx)
        known = {str(item) for item in params.get("known_ids") or []}
        ignore_known = bool(params.get("ignore_known"))
        start_page = int(params.get("start_page") or 0)
        limit = int(params.get("max_pages") or _MAX_PAGES)
        window = int(params.get("f_tpr") or 86400)
        country = str(params.get("country") or "")
        for page in range(start_page, start_page + limit):
            html = _search_html(http, query, geo_id, window, page)
            cards = parse_cards(html, country)
            if not cards and empty_is_throttle(html, 0):
                html = _search_html(http, query, geo_id, window, page, pause=True)
                cards = parse_cards(html, country)
                if not cards and empty_is_throttle(html, 0):
                    raise SourceBlocked(self.id, 429)
            if not cards:
                return
            if not ignore_known and all(card.source_job_id in known for card in cards):
                return
            fresh = [card for card in cards if card.source_job_id not in known]
            short = len(cards) < 10
            resume = None if short else page + 1
            if fresh or resume is not None:
                yield FetchBatch(postings=fresh, resume_page=resume)
            if short:
                return


def fetch_detail(http: HttpClient, job_id: str) -> dict[str, Any]:
    """Description, seniority, industry, and an offsite apply link when LinkedIn has one.

    A 429 is a short throttle, so it is retried. A 404 means the job is gone.
    A 999 is an IP block: it stops the queue instead of burning an attempt.
    """
    url = _DETAIL.format(job_id=job_id)
    waits = iter(_RETRY_AFTER)
    network_retried = False
    while True:
        try:
            response = http.get(url, "linkedin_guest")
        except SourceBlocked as exc:
            if exc.status_code != 429:
                raise
            delay = next(waits, None)
            if delay is None:
                raise
            http._sleep(delay + http._uniform(0.0, 1.0))
            continue
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                raise PostingGone(job_id) from exc
            if status == 999:
                raise SourceBlocked("linkedin_guest", 999) from exc
            raise
        except RetryError as exc:
            # The shared client retries a 999 as if it were a 5xx, then raises this.
            response = exc.last_attempt.result()
            code = getattr(response, "status_code", None)
            if code == 999:
                raise SourceBlocked("linkedin_guest", 999) from exc
            raise
        except httpx.TransportError:
            if network_retried:
                raise
            network_retried = True
            continue
        _reject_authwall(response.text)
        return parse_detail(response.text)


def parse_cards(html: str, country: str) -> list[RawPosting]:
    _reject_authwall(html)
    soup = BeautifulSoup(html, "html.parser")
    postings: list[RawPosting] = []
    for card in soup.select("[data-entity-urn]"):
        urn = str(card.get("data-entity-urn") or "")
        job_id = urn.rsplit(":", 1)[-1]
        if not job_id.isdigit():
            continue
        title = _text(card.select_one(".base-search-card__title"))
        company = _text(card.select_one(".base-search-card__subtitle"))
        if not title or not company:
            continue
        link = card.select_one("a.base-card__full-link")
        href = (
            str(link.get("href") if link else "") or f"https://www.linkedin.com/jobs/view/{job_id}"
        )
        href = href.split("?", 1)[0]
        when = card.select_one("time")
        posted = _posted(str(when.get("datetime")) if when and when.get("datetime") else None)
        postings.append(
            RawPosting(
                source_id="linkedin_guest",
                source_job_id=job_id,
                source_url=href,
                apply_url=href,
                company_name=company,
                title=title,
                location_raw=_text(card.select_one(".job-search-card__location")),
                posted_at=posted,
                payload={"country": country, "urn": urn},
            )
        )
    return postings


def parse_detail(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    markup = soup.select_one(".show-more-less-html__markup")
    criteria: dict[str, str] = {}
    for item in soup.select(".description__job-criteria-item"):
        label = _text(item.select_one(".description__job-criteria-subheader"))
        value = _text(item.select_one(".description__job-criteria-text"))
        if label and value:
            criteria[label.lower()] = value
    apply = _ATS.search(html)
    return {
        "description_html": str(markup) if markup else None,
        "level_hint": criteria.get("seniority level"),
        "industry_hint": criteria.get("industries"),
        "employment_type_raw": criteria.get("employment type"),
        "apply_url": apply.group(0) if apply else None,
    }


def _search_html(
    http: HttpClient,
    query: str,
    geo_id: str,
    window: int,
    page: int,
    *,
    pause: bool = False,
) -> str:
    if pause:
        http._sleep(45)  # one retry after a silent throttle; tests inject the sleep
    try:
        response = http.get(
            _SEARCH + _query(query, geo_id, window, page),
            "linkedin_guest",
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 999:
            raise SourceBlocked("linkedin_guest", 999) from exc
        raise
    _reject_authwall(response.text)
    return response.text


def _query(query: str, geo_id: str, window: int, page: int) -> str:
    from urllib.parse import urlencode

    return "?" + urlencode(
        {
            "keywords": query,
            "geoId": geo_id,
            "f_TPR": f"r{window}",
            "start": str(page * 10),
        }
    )


def _client(ctx: FetchContext) -> HttpClient:
    if ctx.http is not None and ctx.http._min_delay >= 6:
        return ctx.http
    browser = httpx.Client(
        timeout=httpx.Timeout(30.0),
        headers={"User-Agent": _BROWSER, "Accept-Language": "en-US,en;q=0.9"},
        follow_redirects=True,
    )
    return HttpClient(browser, min_delay=6.0, max_delay=8.0)


def _reject_authwall(html: str) -> None:
    lowered = html.lower()
    if "authwall" in lowered or "captcha" in lowered:
        raise RunPartial("linkedin_guest", "LinkedIn asked for a login or captcha")


def _text(node: Any) -> str | None:
    if node is None:
        return None
    value = node.get_text(" ", strip=True)
    return value or None


def _posted(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None
