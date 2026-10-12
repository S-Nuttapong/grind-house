"""Greenhouse public job board API."""

import html
from collections.abc import Iterator
from typing import Any

import httpx

from jobhunt.core.http import SourceBlocked
from jobhunt.facts.api_fields import from_payload
from jobhunt.scrape.sources.base import (
    CompanyTarget,
    FetchBatch,
    FetchContext,
    RawPosting,
    ScopeView,
)
from jobhunt.scrape.sources.parse import as_date, selected

BOARD_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"


class GreenhouseSource:
    id = "greenhouse"
    kind = "ats"
    full_board = True

    def fetch(self, scope: ScopeView, ctx: FetchContext) -> Iterator[FetchBatch]:
        for company in ctx.companies:
            if company.ats_slug == "" or not selected(company, scope.params):
                continue
            yield _fetch_company(ctx, company)


def _fetch_company(ctx: FetchContext, company: CompanyTarget) -> FetchBatch:
    url = BOARD_URL.format(slug=company.ats_slug)
    try:
        response = ctx.http.get(url, GreenhouseSource.id)
    except SourceBlocked:
        raise
    except httpx.HTTPStatusError as exc:
        missing = exc.response.status_code == 404
        return FetchBatch(company_id=company.id, failed=True, clear_ats=missing)
    payload = response.json()
    postings = [
        mapped
        for item in payload.get("jobs") or []
        if (mapped := map_job(item, company.name, company.ats_slug)) is not None
    ]
    return FetchBatch(company_id=company.id, postings=postings)


def map_job(item: dict[str, Any], company_name: str, slug: str) -> RawPosting | None:
    title = _text(item.get("title"))
    source_url = _text(item.get("absolute_url"))
    job_id = item.get("id")
    if not title or not source_url or job_id is None:
        return None
    location = item.get("location") or {}
    location_name = location.get("name") if isinstance(location, dict) else None
    content = item.get("content")
    description = html.unescape(content) if isinstance(content, str) else None
    name = _text(item.get("company_name")) or company_name
    detail = from_payload("greenhouse", item)
    pay = detail.pay.value if detail.pay is not None else None
    shown = _text(location_name)
    if shown and shown.casefold() in {
        "n/a",
        "na",
        "hybrid",
        "remote",
        "in-office",
        "distributed",
        "multiple locations",
    }:
        shown = None
    if shown is None and detail.locations is not None and detail.locations.value:
        place = detail.locations.value[0]
        shown = ", ".join(part for part in (place.city, place.region, place.country) if part)
    return RawPosting(
        source_id="greenhouse",
        source_job_id=str(job_id),
        source_url=source_url,
        apply_url=source_url,
        company_name=name,
        company_hint={"ats": "greenhouse", "slug": slug},
        title=title,
        location_raw=shown,
        description_html=description,
        posted_at=as_date(item.get("first_published") or item.get("updated_at")),
        employment_type_raw=detail.job_type.value if detail.job_type is not None else None,
        salary_min=None if pay is None else pay.minimum,
        salary_max=None if pay is None else pay.maximum,
        salary_currency=None if pay is None else pay.currency,
        salary_interval_raw=None if pay is None else pay.interval,
        remote_hint=detail.workplace.value if detail.workplace is not None else None,
        payload=item,
    )


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
