"""Adzuna job search API.

No feed for Thailand, Taiwan, Japan, Hong Kong, Malaysia, Vietnam, or Indonesia.
"""

import os
from collections.abc import Iterator
from typing import Any

from jobhunt.scrape.sources.base import FetchBatch, FetchContext, RawPosting, RunPartial, ScopeView
from jobhunt.scrape.sources.fetch import read_json
from jobhunt.scrape.sources.parse import as_date, as_decimal, as_dict

# Documented search countries. See https://developer.adzuna.com/docs/search
_COUNTRIES = {
    "au": "Australia",
    "de": "Germany",
    "fr": "France",
    "gb": "United Kingdom",
    "in": "India",
    "nl": "Netherlands",
    "nz": "New Zealand",
    "sg": "Singapore",
}
# The search payload has amounts but no currency code. The feed country is the currency.
_CURRENCY = {
    "au": "AUD",
    "de": "EUR",
    "fr": "EUR",
    "gb": "GBP",
    "in": "INR",
    "nl": "EUR",
    "nz": "NZD",
    "sg": "SGD",
}
_PAGE = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"
_CAP = 50


class AdzunaSource:
    id = "adzuna"
    kind = "aggregator"
    full_board = False

    def fetch(self, scope: ScopeView, ctx: FetchContext) -> Iterator[FetchBatch]:
        params = scope.params
        country = _text(params.get("country"))
        if country is None or country.lower() not in _COUNTRIES:
            raise RunPartial(self.id, "country is not an Adzuna feed")
        code = country.lower()
        search = _text(params.get("search_term"))
        if search is None:
            raise RunPartial(self.id, "search_term is required")
        app_id = os.environ.get("ADZUNA_APP_ID", "").strip()
        app_key = os.environ.get("ADZUNA_APP_KEY", "").strip()
        if not app_id or not app_key:
            raise RunPartial(self.id, "ADZUNA_APP_ID and ADZUNA_APP_KEY are not set")
        wanted = _cap(_int(params.get("results_wanted"), _CAP))
        query = {
            "app_id": app_id,
            "app_key": app_key,
            "what": search,
            "results_per_page": str(wanted),
            "content-type": "application/json",
        }
        where = _text(params.get("location"))
        if where:
            query["where"] = where
        payload = read_json(
            ctx,
            self.id,
            "GET",
            _PAGE.format(country=code),
            params=query,
            headers={"Accept": "application/json"},
        )
        rows = payload.get("results") if isinstance(payload, dict) else None
        postings = [
            mapped
            for item in rows or []
            if isinstance(item, dict)
            and (mapped := map_job(item, _COUNTRIES[code], _CURRENCY[code])) is not None
        ]
        yield FetchBatch(postings=postings)


def map_job(item: dict[str, Any], country_name: str, currency: str) -> RawPosting | None:
    title = _text(item.get("title"))
    source_url = _text(item.get("redirect_url"))
    company = as_dict(item.get("company"))
    company_name = _text(company.get("display_name"))
    job_id = _text(item.get("id"))
    if not title or not source_url or not company_name or not job_id:
        return None
    location = as_dict(item.get("location"))
    display = _text(location.get("display_name")) or ""
    if country_name.lower() in display.lower():
        place = display
    else:
        place = f"{display}, {country_name}".strip(", ")
    category = as_dict(item.get("category"))
    contract = _text(item.get("contract_time")) or _text(item.get("contract_type"))
    disclosed = not _predicted(item.get("salary_is_predicted"))
    return RawPosting(
        source_id="adzuna",
        source_job_id=job_id,
        source_url=source_url,
        apply_url=source_url,
        company_name=company_name,
        title=title,
        location_raw=place or None,
        description_text=_text(item.get("description")),
        posted_at=as_date(item.get("created")),
        employment_type_raw=contract,
        salary_min=as_decimal(item.get("salary_min")) if disclosed else None,
        salary_max=as_decimal(item.get("salary_max")) if disclosed else None,
        salary_currency=currency if disclosed and item.get("salary_min") is not None else None,
        salary_interval_raw="yearly" if disclosed and item.get("salary_min") is not None else None,
        level_hint=_text(category.get("label")),
        role_hint=_text(category.get("label")),
        industry_hint=_text(category.get("label")),
        payload=item,
    )


def _predicted(value: Any) -> bool:
    return value not in (None, 0, False, "0", "false", "False")


def _cap(wanted: int) -> int:
    return max(1, min(wanted, _CAP))


def _int(value: Any, default: int) -> int:
    if value in (None, ""):
        return default
    return int(value)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
