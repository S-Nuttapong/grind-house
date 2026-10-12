"""Ashby public posting API."""

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import httpx

from jobhunt.core.http import SourceBlocked
from jobhunt.facts.base import JobDetail, Pay, PayFact, Place
from jobhunt.facts.mapping import location_fact, map_job_type, map_workplace, text, text_fact
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

BOARD_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"

_INTERVALS = {
    "1 YEAR": "yearly",
    "YEAR": "yearly",
    "1 MONTH": "monthly",
    "MONTH": "monthly",
    "1 WEEK": "weekly",
    "1 DAY": "daily",
    "1 HOUR": "hourly",
    "HOUR": "hourly",
}


class AshbySource(SourceDefaults):
    id = "ashby"
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
        response = ctx.http.get(url, AshbySource.id)
    except SourceBlocked:
        raise
    except httpx.HTTPStatusError as exc:
        missing = exc.response.status_code == 404
        return FetchBatch(company_id=company.id, failed=True, clear_ats=missing)
    payload = response.json()
    postings = [
        mapped
        for item in payload.get("jobs") or []
        if isinstance(item, dict) and (mapped := map_job(item, company.name, company.ats_slug))
    ]
    return FetchBatch(company_id=company.id, postings=postings)


def map_job(item: dict[str, Any], company_name: str, slug: str) -> RawPosting | None:
    title = _text(item.get("title"))
    source_url = _text(item.get("jobUrl"))
    job_id = item.get("id")
    if not title or not source_url or not job_id:
        return None
    salary_min, salary_max, currency, interval = _salary(item.get("compensation"))
    remote_hint = _text(item.get("workplaceType"))
    if remote_hint is None and item.get("isRemote") is True:
        remote_hint = "remote"
    location_raw = _text(item.get("location"))
    if location_raw is None:
        detail = _facts(item)
        if detail.locations is not None and detail.locations.value:
            place = detail.locations.value[0]
            location_raw = ", ".join(
                part for part in (place.city, place.region, place.country) if part
            )
    return RawPosting(
        source_id="ashby",
        source_job_id=str(job_id),
        source_url=source_url,
        apply_url=_text(item.get("applyUrl")) or source_url,
        company_name=company_name,
        company_hint={"ats": "ashby", "slug": slug},
        title=title,
        location_raw=location_raw,
        remote_hint=remote_hint,
        description_html=_text(item.get("descriptionHtml")),
        description_text=_text(item.get("descriptionPlain")),
        posted_at=as_date(item.get("publishedAt")),
        employment_type_raw=_text(item.get("employmentType")),
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=currency,
        salary_interval_raw=interval,
        payload=item,
    )


def _salary(compensation: Any) -> tuple[Any, Any, str | None, str | None]:
    if not isinstance(compensation, dict):
        return None, None, None, None
    components = compensation.get("summaryComponents") or []
    for component in components:
        if not isinstance(component, dict):
            continue
        if str(component.get("compensationType") or "").lower() != "salary":
            continue
        low = as_decimal(component.get("minValue"))
        high = as_decimal(component.get("maxValue"))
        if low is None and high is None:
            continue
        raw_interval = str(component.get("interval") or "").upper()
        return low, high, _text(component.get("currencyCode")), _INTERVALS.get(raw_interval)
    return None, None, None, None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _facts(payload: dict[str, Any]) -> JobDetail:
    places: list[Place] = []
    raw = payload.get("location")
    if isinstance(raw, str):
        places.extend(place for place in resolve_places(raw) if place not in places)
    secondary = payload.get("secondaryLocations")
    if isinstance(secondary, list):
        for item in secondary:
            raw_item = item.get("location") if isinstance(item, dict) else item
            if isinstance(raw_item, str):
                places.extend(place for place in resolve_places(raw_item) if place not in places)
    address = payload.get("address")
    postal = address.get("postalAddress") if isinstance(address, dict) else None
    if isinstance(postal, dict):
        locality = text(postal.get("addressLocality"))
        country = text(postal.get("addressCountry"))
        joined = ", ".join(part for part in (locality, country) if part)
        if joined:
            places.extend(place for place in resolve_places(joined) if place not in places)
    workplace = text(payload.get("workplaceType"))
    if workplace is None and payload.get("isRemote") is True:
        workplace = "remote"
    return JobDetail(
        pay=_compensation(payload.get("compensation")),
        job_type=text_fact(
            map_job_type(text(payload.get("employmentType"))),
            text(payload.get("employmentType")),
            "api:ashby",
        ),
        workplace=text_fact(map_workplace(workplace), workplace, "api:ashby"),
        locations=location_fact(places, "api:ashby"),
    )


def _compensation(compensation: object) -> PayFact | None:
    if not isinstance(compensation, dict):
        return None
    components = compensation.get("summaryComponents")
    if not isinstance(components, list):
        return None
    for component in components:
        if not isinstance(component, dict):
            continue
        if str(component.get("compensationType") or "").casefold() != "salary":
            continue
        low = as_decimal(component.get("minValue"))
        high = as_decimal(component.get("maxValue"))
        currency = text(component.get("currencyCode"))
        if low is None and high is None or currency is None:
            continue
        interval = str(component.get("interval") or "").upper()
        return PayFact(
            value=Pay(
                minimum=low,
                maximum=high,
                currency=currency.upper(),
                interval=_interval(interval),
            ),
            confidence=1.0,
            evidence=str(component),
            parser_id="api:ashby",
        )
    return None


def _interval(value: str) -> str | None:
    if "YEAR" in value:
        return "yearly"
    if "MONTH" in value:
        return "monthly"
    if "WEEK" in value:
        return "weekly"
    if "DAY" in value:
        return "daily"
    if "HOUR" in value:
        return "hourly"
    return None
