"""SEEK-family search: JobsDB, JobStreet, and Seek share one API."""

from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import httpx

from jobhunt.core.http import HttpClient, SourceBlocked
from jobhunt.facts.base import JobDetail, Place
from jobhunt.facts.mapping import location_fact, text
from jobhunt.scrape.sources.base import (
    FetchBatch,
    FetchContext,
    RawPosting,
    RunPartial,
    ScopeView,
    SourceDefaults,
    SourceSpec,
)
from jobhunt.scrape.sources.fetch import read_json
from jobhunt.scrape.sources.parse import as_dict

_QUERY = """
query jobDetails($jobId: ID!) {
  jobDetails(id: $jobId) {
    job {
      id
      content(platform: WEB)
      salary { label }
    }
  }
}
"""
_MAX_PAGES = 5
_BROWSER = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)


class SeekSource(SourceDefaults):
    id = "seek"
    kind = "aggregator"
    full_board = False
    needs_detail_fetch = True
    spec = SourceSpec(
        kind="aggregator",
        min_interval=timedelta(minutes=15),
        close_after=timedelta(days=14),
    )

    def payload_facts(self, payload: dict[str, Any]) -> JobDetail:
        country = text(payload.get("country"))
        if country is None or len(country) != 2:
            return JobDetail()
        return JobDetail(locations=location_fact([Place(country=country.upper())], "api:seek"))

    def augment_text(self, payload: dict[str, Any], text_value: str) -> str:
        label = payload.get("salary")
        if not isinstance(label, str) or not label.strip():
            return text_value
        return f"{text_value}\nSalary: {label.strip()}\n"

    def fetch(self, scope: ScopeView, ctx: FetchContext) -> Iterator[FetchBatch]:
        params = scope.params
        host = str(params.get("host") or "")
        site_key = str(params.get("site_key") or "")
        query = str(params.get("search_term") or "")
        if not host or not site_key or not query:
            raise RunPartial(self.id, "host, site_key, and search_term are required")
        http = _client(ctx)
        known = {str(item) for item in params.get("known_ids") or []}
        ignore_known = bool(params.get("ignore_known"))
        country = str(params.get("country") or "")
        date_range = int(params.get("date_range") or 1)
        start_page = int(params.get("start_page") or 1)
        limit = int(params.get("max_pages") or _MAX_PAGES)
        collected: list[RawPosting] = []
        stopped = "cap"
        for page in range(start_page, start_page + limit):
            try:
                payload = read_json(
                    _context(ctx, http),
                    self.id,
                    "GET",
                    f"https://{host}/api/jobsearch/v5/search",
                    params={
                        "siteKey": site_key,
                        "keywords": query,
                        "classification": "6281",
                        "page": str(page),
                        "pageSize": "100",
                        "sortmode": "ListedDate",
                        "dateRange": str(date_range),
                    },
                    headers={"Accept": "application/json", "User-Agent": _BROWSER},
                )
            except SourceBlocked:
                raise
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {403, 429}:
                    raise SourceBlocked(self.id, exc.response.status_code) from exc
                raise RunPartial(self.id, f"HTTP {exc.response.status_code}") from exc
            rows = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(rows, list) or not rows:
                stopped = "short"
                break
            cards = [
                mapped
                for row in rows
                if isinstance(row, dict) and (mapped := map_job(host, country, row))
            ]
            if not ignore_known and cards and all(card.source_job_id in known for card in cards):
                stopped = "known"
                break
            collected.extend(card for card in cards if card.source_job_id not in known)
            if len(rows) < 100:
                stopped = "short"
                break
        resume = start_page + limit if stopped == "cap" else None
        yield FetchBatch(postings=collected, resume_page=resume)


def fetch_detail(http: HttpClient, host: str, job_id: str) -> str | None:
    """Full description HTML. Search results only carry a short teaser."""
    payload = read_json(
        _context_from(http),
        "seek",
        "POST",
        f"https://{host}/graphql",
        json={"operationName": "jobDetails", "variables": {"jobId": job_id}, "query": _QUERY},
        headers={"Accept": "application/json", "User-Agent": _BROWSER},
    )
    job = as_dict(as_dict(as_dict(payload.get("data")).get("jobDetails")).get("job"))
    content = job.get("content")
    return str(content) if content else None


def map_job(host: str, country: str, row: dict[str, Any]) -> RawPosting | None:
    job_id = str(row.get("id") or "")
    title = str(row.get("title") or "").strip()
    advertiser = as_dict(row.get("advertiser"))
    company = str(advertiser.get("description") or row.get("companyName") or "").strip()
    if not job_id or not title or not company:
        return None
    locations = row.get("locations")
    place = as_dict(locations[0]) if isinstance(locations, list) and locations else {}
    classifications = row.get("classifications")
    kind = {}
    if isinstance(classifications, list) and classifications:
        kind = as_dict(classifications[0])
    sub = as_dict(kind.get("subclassification"))
    parent = as_dict(kind.get("classification")).get("description")
    role_hint = str(sub.get("description") or parent or "")
    arrangements = as_dict(row.get("workArrangements")).get("data")
    remote = None
    if isinstance(arrangements, list) and arrangements:
        remote = str(as_dict(as_dict(arrangements[0]).get("label")).get("text") or "") or None
    listed = row.get("listingDate")
    posted = None
    if isinstance(listed, str) and listed:
        posted = datetime.fromisoformat(listed.replace("Z", "+00:00")).date()
    return RawPosting(
        source_id="seek",
        source_job_id=job_id,
        source_url=_job_url(host, job_id),
        apply_url=_job_url(host, job_id),
        company_name=company,
        title=title,
        location_raw=str(place.get("label") or "") or None,
        remote_hint=remote,
        description_text=str(row.get("teaser") or "") or None,
        posted_at=posted,
        salary_interval_raw=None,
        role_hint=role_hint or None,
        industry_hint=role_hint or None,
        payload={"country": country, "host": host, "salary": row.get("salaryLabel")},
    )


def _job_url(host: str, job_id: str) -> str:
    path = "/id/job/" if host.startswith("id.") else "/job/"
    return f"https://{host}{path}{job_id}"


def _client(ctx: FetchContext) -> HttpClient:
    if ctx.http._min_delay >= 2 and ctx.http._min_delay < 6:
        return ctx.http
    browser = httpx.Client(
        timeout=httpx.Timeout(30.0),
        headers={"User-Agent": _BROWSER, "Accept": "application/json"},
        follow_redirects=True,
    )
    return HttpClient(browser, min_delay=2.0, max_delay=3.0)


def _context(ctx: FetchContext, http: HttpClient) -> FetchContext:
    if ctx.http is http:
        return ctx
    return FetchContext(http=http, companies=ctx.companies)


def _context_from(http: HttpClient) -> FetchContext:
    return FetchContext(http=http, companies=[])
