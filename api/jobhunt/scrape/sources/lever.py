"""Lever public postings API."""

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import httpx

from jobhunt.core.http import SourceBlocked
from jobhunt.facts.base import JobDetail, Pay, PayFact, Place
from jobhunt.facts.mapping import (
    interval_word,
    location_fact,
    map_job_type,
    map_workplace,
    text_fact,
)
from jobhunt.facts.mapping import text as plain
from jobhunt.facts.places import resolve_places
from jobhunt.scrape.sources.base import (
    CompanyTarget,
    FetchBatch,
    FetchContext,
    RawPosting,
    ScopeView,
    SourceDefaults,
    SourceSpec,
)
from jobhunt.scrape.sources.parse import as_date, as_decimal, selected

BOARD_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"


class LeverSource(SourceDefaults):
    id = "lever"
    kind = "ats"
    full_board = True
    spec = SourceSpec(kind="ats", min_interval=timedelta(hours=6))

    def payload_facts(self, payload: dict[str, Any]) -> JobDetail:
        return _facts(payload)

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
    detail = _facts(item)
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
    cleaned = str(value).strip()
    return cleaned or None


def _facts(payload: dict[str, Any]) -> JobDetail:
    categories = payload.get("categories") if isinstance(payload.get("categories"), dict) else {}
    places: list[Place] = []
    raw_locations = categories.get("allLocations") if isinstance(categories, dict) else None
    if isinstance(raw_locations, list):
        for item in raw_locations:
            if isinstance(item, str):
                places.extend(place for place in resolve_places(item) if place not in places)
    single = categories.get("location") if isinstance(categories, dict) else None
    if isinstance(single, str):
        places.extend(place for place in resolve_places(single) if place not in places)
    country = payload.get("country")
    if isinstance(country, str) and len(country.strip()) == 2 and not places:
        places.append(Place(country=country.strip().upper()))
    commitment = categories.get("commitment") if isinstance(categories, dict) else None
    return JobDetail(
        pay=_pay(payload.get("salaryRange")),
        job_type=text_fact(
            map_job_type(commitment if isinstance(commitment, str) else None),
            commitment if isinstance(commitment, str) else None,
            "api:lever",
        ),
        workplace=text_fact(
            map_workplace(plain(payload.get("workplaceType"))),
            plain(payload.get("workplaceType")),
            "api:lever",
        ),
        locations=location_fact(places, "api:lever"),
    )


def _pay(raw: object) -> PayFact | None:
    if not isinstance(raw, dict):
        return None
    low = as_decimal(raw.get("min"))
    high = as_decimal(raw.get("max"))
    currency = plain(raw.get("currency"))
    if low is None and high is None or currency is None:
        return None
    return PayFact(
        value=Pay(
            minimum=low,
            maximum=high,
            currency=currency.upper(),
            interval=interval_word(plain(raw.get("interval"))),
        ),
        confidence=1.0,
        evidence=str(raw),
        parser_id="api:lever",
    )
