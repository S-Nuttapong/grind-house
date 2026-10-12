"""Reed.co.uk Jobseeker API. United Kingdom only."""

import os
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any

from jobhunt.scrape.sources.base import FetchBatch, FetchContext, RawPosting, RunPartial, ScopeView
from jobhunt.scrape.sources.fetch import read_json
from jobhunt.scrape.sources.parse import as_date, as_decimal

_SEARCH = "https://www.reed.co.uk/api/1.0/search"
_CAP = 50


class ReedSource:
    id = "reed"
    kind = "aggregator"
    full_board = False

    def fetch(self, scope: ScopeView, ctx: FetchContext) -> Iterator[FetchBatch]:
        search = _text(scope.params.get("search_term"))
        if search is None:
            raise RunPartial(self.id, "search_term is required")
        api_key = os.environ.get("REED_API_KEY", "").strip()
        if not api_key:
            raise RunPartial(self.id, "REED_API_KEY is not set")
        wanted = _cap(_int(scope.params.get("results_wanted"), _CAP))
        query = {"keywords": search, "resultsToTake": str(wanted)}
        location = _text(scope.params.get("location"))
        if location:
            query["locationName"] = location
        payload = read_json(
            ctx,
            self.id,
            "GET",
            _SEARCH,
            params=query,
            auth=(api_key, ""),
            headers={"Accept": "application/json"},
        )
        rows = payload.get("results") if isinstance(payload, dict) else None
        postings = [
            mapped
            for item in rows or []
            if isinstance(item, dict) and (mapped := map_job(item)) is not None
        ]
        yield FetchBatch(postings=postings)


def map_job(item: dict[str, Any]) -> RawPosting | None:
    title = _text(item.get("jobTitle"))
    source_url = _text(item.get("jobUrl"))
    company = _text(item.get("employerName"))
    job_id = item.get("jobId")
    if not title or not source_url or not company or job_id is None:
        return None
    low = item.get("minimumSalary")
    high = item.get("maximumSalary")
    has_salary = low not in (None, "") or high not in (None, "")
    place = _text(item.get("locationName"))
    location = f"{place}, United Kingdom" if place else "United Kingdom"
    return RawPosting(
        source_id="reed",
        source_job_id=str(job_id),
        source_url=source_url,
        apply_url=_text(item.get("externalUrl")) or source_url,
        company_name=company,
        title=title,
        location_raw=location,
        description_text=_text(item.get("jobDescription")),
        posted_at=_reed_date(item.get("date")),
        employment_type_raw=None,
        salary_min=as_decimal(low) if has_salary else None,
        salary_max=as_decimal(high) if has_salary else None,
        salary_currency=_text(item.get("currency")) or ("GBP" if has_salary else None),
        # Search results are annual figures. The per-job endpoint has the pay period.
        salary_interval_raw="yearly" if has_salary else None,
        payload=item,
    )


def _reed_date(value: Any) -> date | None:
    text = _text(value)
    if text is None:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return as_date(text)


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
