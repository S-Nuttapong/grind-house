"""Greenhouse public job board API."""

import html
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import httpx

from jobhunt.core.http import SourceBlocked
from jobhunt.facts.base import JobDetail, Pay, PayFact, Place
from jobhunt.facts.mapping import (
    decimal_named,
    flat,
    location_fact,
    map_job_type,
    map_workplace,
    metadata,
    text,
    text_fact,
)
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

BOARD_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"


class GreenhouseSource(SourceDefaults):
    id = "greenhouse"
    kind = "ats"
    full_board = True
    spec = SourceSpec(kind="ats", min_interval=timedelta(hours=6))

    def payload_facts(self, payload: dict[str, Any]) -> JobDetail:
        return _facts(payload)

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
    detail = _facts(item)
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
    cleaned = str(value).strip()
    return cleaned or None


_PLACEHOLDERS = {
    "n/a",
    "na",
    "hybrid",
    "remote",
    "in-office",
    "in office",
    "distributed",
    "multiple locations",
    "anywhere",
}
_PAY_NAMES = {"minimum salary", "maximum salary", "pay transparency range"}
_TYPE_NAMES = {"employment type", "time type", "job type"}
_WORK_NAMES = {"workplace type", "position open to remote"}


def _facts(payload: dict[str, Any]) -> JobDetail:
    meta = metadata(payload)
    places = _offices(payload)
    raw_name = _location_name(payload)
    placeholder = raw_name is not None and raw_name.casefold() in _PLACEHOLDERS
    workplace = map_workplace(raw_name) if placeholder else None
    if raw_name and raw_name.casefold() not in _PLACEHOLDERS:
        for place in resolve_places(raw_name):
            if place not in places:
                places.append(place)
    type_text = _named(meta, _TYPE_NAMES)
    work_text = _named(meta, _WORK_NAMES)
    return JobDetail(
        pay=_pay_from_metadata(meta),
        job_type=text_fact(map_job_type(type_text), type_text, "api:greenhouse"),
        workplace=text_fact(
            map_workplace(work_text) or workplace,
            work_text or raw_name,
            "api:greenhouse",
        ),
        locations=location_fact(places, "api:greenhouse"),
    )


def _offices(payload: dict[str, Any]) -> list[Place]:
    offices = payload.get("offices")
    if not isinstance(offices, list):
        return []
    places: list[Place] = []
    for office in offices:
        if not isinstance(office, dict):
            continue
        raw = office.get("location") or office.get("name")
        if not isinstance(raw, str) or raw.casefold() in _PLACEHOLDERS:
            continue
        for place in resolve_places(raw):
            if place not in places:
                places.append(place)
    return places


def _pay_from_metadata(meta: list[dict[str, Any]]) -> PayFact | None:
    for item in meta:
        name = str(item.get("name") or "").casefold()
        if "budget" in name:
            continue
        if name not in _PAY_NAMES and "salary range" not in name and "pay range" not in name:
            continue
        pay = _currency_range(item.get("value"))
        if pay is None:
            continue
        evidence = str(item.get("value"))
        return PayFact(value=pay, confidence=1.0, evidence=evidence, parser_id="api:greenhouse")
    low = decimal_named(meta, "minimum salary")
    high = decimal_named(meta, "maximum salary")
    if low is None and high is None:
        return None
    return PayFact(
        value=Pay(minimum=low, maximum=high, currency="USD", interval="yearly"),
        confidence=1.0,
        evidence=f"{low}-{high}",
        parser_id="api:greenhouse",
    )


def _named(meta: list[dict[str, Any]], names: set[str]) -> str | None:
    for item in meta:
        if str(item.get("name") or "").casefold() in names:
            return flat(item.get("value"))
    return None


def _currency_range(value: object) -> Pay | None:
    if not isinstance(value, dict):
        return None
    low = as_decimal(value.get("min_value"))
    high = as_decimal(value.get("max_value"))
    currency = text(value.get("unit"))
    if currency is None or (low is None and high is None):
        return None
    return Pay(minimum=low, maximum=high, currency=currency.upper(), interval="yearly")


def _location_name(payload: dict[str, Any]) -> str | None:
    location = payload.get("location")
    if isinstance(location, dict):
        return text(location.get("name"))
    return None
