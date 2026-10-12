"""Lever public postings API."""

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

BOARD_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"


class LeverSource:
    id = "lever"
    kind = "ats"
    full_board = True

    def fetch(self, scope: ScopeView, ctx: FetchContext) -> Iterator[FetchBatch]:
        for company in ctx.companies:
            if not company.ats_slug or not selected(company, scope.params):
                continue
            yield _fetch_company(ctx, company)


def _fetch_company(ctx: FetchContext, company: CompanyTarget) -> FetchBatch:
    url = BOARD_URL.format(slug=company.ats_slug)
    try:
        response = ctx.http.get(url, LeverSource.id)
    except SourceBlocked:
        raise
    except httpx.HTTPStatusError as exc:
        missing = exc.response.status_code == 404
        return FetchBatch(company_id=company.id, failed=True, clear_ats=missing)
    payload = response.json()
    items = payload if isinstance(payload, list) else []
    postings = [
        mapped
        for item in items
        if isinstance(item, dict) and (mapped := map_job(item, company.name, company.ats_slug))
    ]
    return FetchBatch(company_id=company.id, postings=postings)


def map_job(item: dict[str, Any], company_name: str, slug: str) -> RawPosting | None:
    title = _text(item.get("text"))
    source_url = _text(item.get("hostedUrl"))
    job_id = item.get("id")
    if not title or not source_url or not job_id:
        return None
    categories = item.get("categories") or {}
    location = categories.get("location") if isinstance(categories, dict) else None
    detail = from_payload("lever", item)
    pay = detail.pay.value if detail.pay is not None else None
    return RawPosting(
        source_id="lever",
        source_job_id=str(job_id),
        source_url=source_url,
        apply_url=_text(item.get("applyUrl")) or source_url,
        company_name=company_name,
        company_hint={"ats": "lever", "slug": slug},
        title=title,
        location_raw=_text(location),
        remote_hint=_text(item.get("workplaceType")),
        description_html=description_html(item),
        description_text=_text(item.get("descriptionPlain")),
        posted_at=as_date(item.get("createdAt")),
        employment_type_raw=_text(categories.get("commitment"))
        if isinstance(categories, dict)
        else None,
        salary_min=None if pay is None else pay.minimum,
        salary_max=None if pay is None else pay.maximum,
        salary_currency=None if pay is None else pay.currency,
        salary_interval_raw=None if pay is None else pay.interval,
        payload=item,
    )


def description_html(item: dict[str, Any]) -> str | None:
    parts: list[str] = []
    opening = item.get("description") or item.get("descriptionPlain")
    if isinstance(opening, str) and opening.strip():
        parts.append(opening)
    for block in item.get("lists") or []:
        if not isinstance(block, dict):
            continue
        heading = _text(block.get("text"))
        if heading:
            parts.append(f"<h3>{heading}</h3>")
        content = block.get("content")
        if isinstance(content, str) and content.strip():
            parts.append(content)
    extra = item.get("additional") or item.get("additionalPlain")
    if isinstance(extra, str) and extra.strip():
        parts.append(extra)
    if not parts:
        return None
    return "\n".join(parts)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
