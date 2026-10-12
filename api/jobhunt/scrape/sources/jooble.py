"""Jooble REST API. Each country host needs its own key. See Jooble's API docs.

The free plan is 500 requests per key for the life of the key, so a scope asks
for one page. Vietnam has no ``vn.jooble.org`` host and is omitted.
"""

import json
import os
import re
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

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
from jobhunt.scrape.sources.parse import as_date

_HOSTS = {
    "TH": "th.jooble.org",
    "GB": "uk.jooble.org",
    "UK": "uk.jooble.org",
    "DE": "de.jooble.org",
    "NL": "nl.jooble.org",
    "FR": "fr.jooble.org",
    "SG": "sg.jooble.org",
    "AU": "au.jooble.org",
    "NZ": "nz.jooble.org",
    "JP": "jp.jooble.org",
    "TW": "tw.jooble.org",
    "HK": "hk.jooble.org",
    "MY": "my.jooble.org",
    "ID": "id.jooble.org",
    "IN": "in.jooble.org",
}
_CAP = 20
_AMOUNT = re.compile(r"\d[\d,]*")
_CURRENCY = re.compile(r"\b([A-Z]{3})\b")


class JoobleSource(SourceDefaults):
    id = "jooble"
    kind = "aggregator"
    spec = SourceSpec(
        kind="aggregator",
        min_interval=timedelta(hours=24),
        close_after=timedelta(days=14),
    )
    full_board = False

    def fetch(self, scope: ScopeView, ctx: FetchContext) -> Iterator[FetchBatch]:
        country = (_text(scope.params.get("country")) or "").upper()
        host = _HOSTS.get(country)
        if host is None:
            raise RunPartial(self.id, "country is not a Jooble host")
        search = _text(scope.params.get("search_term"))
        location = _text(scope.params.get("location"))
        if search is None or location is None:
            raise RunPartial(self.id, "search_term and location are required")
        api_key = _key(country)
        if api_key is None:
            raise RunPartial(self.id, f"JOOBLE_API_KEYS has no key for {country}")
        wanted = _cap(_int(scope.params.get("results_wanted"), _CAP))
        payload = read_json(
            ctx,
            self.id,
            "POST",
            f"https://{host}/api/{api_key}",
            json={
                "keywords": search,
                "location": location,
                "radius": "80",
                "page": "1",
                "ResultOnPage": str(wanted),
                "companysearch": False,
            },
            headers={"Accept": "application/json"},
        )
        rows = payload.get("jobs") if isinstance(payload, dict) else None
        postings = [
            mapped
            for item in rows or []
            if isinstance(item, dict) and (mapped := map_job(item)) is not None
        ]
        yield FetchBatch(postings=postings)


def map_job(item: dict[str, Any]) -> RawPosting | None:
    title = _text(item.get("title"))
    source_url = _text(item.get("link"))
    company = _text(item.get("company"))
    job_id = item.get("id")
    if not title or not source_url or not company or job_id is None:
        return None
    low, high, currency = parse_salary(_text(item.get("salary")))
    return RawPosting(
        source_id="jooble",
        source_job_id=str(job_id),
        source_url=source_url,
        apply_url=source_url,
        company_name=company,
        title=title,
        location_raw=_text(item.get("location")),
        description_text=_text(item.get("snippet")),
        posted_at=as_date(item.get("updated")),
        employment_type_raw=_text(item.get("type")),
        salary_min=low,
        salary_max=high,
        salary_currency=currency,
        payload=item,
    )


def parse_salary(text: str | None) -> tuple[Decimal | None, Decimal | None, str | None]:
    """Jooble returns salary as a display string, for example ``17,600 - 20,000 UAH``."""
    if not text:
        return None, None, None
    amounts = [Decimal(part.replace(",", "")) for part in _AMOUNT.findall(text)]
    currency_match = _CURRENCY.search(text)
    currency = currency_match.group(1) if currency_match else None
    if not amounts:
        return None, None, currency
    if len(amounts) == 1:
        return amounts[0], None, currency
    return amounts[0], amounts[1], currency


def _key(country: str) -> str | None:
    raw = os.environ.get("JOOBLE_API_KEYS", "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RunPartial("jooble", "JOOBLE_API_KEYS is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise RunPartial("jooble", "JOOBLE_API_KEYS must be a JSON object")
    value = parsed.get(country) or parsed.get(country.lower())
    text = _text(value)
    return text


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
