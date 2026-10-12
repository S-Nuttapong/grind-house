"""MyCareersFuture public search API. Singapore, no API key.

robots.txt allows the site. The search endpoint is the same one the public
board calls: ``POST /v2/search``.
"""

from collections.abc import Iterator
from typing import Any

from jobhunt.scrape.sources.base import FetchBatch, FetchContext, RawPosting, RunPartial, ScopeView
from jobhunt.scrape.sources.fetch import read_json
from jobhunt.scrape.sources.parse import as_date, as_decimal, as_dict

_SEARCH = "https://api.mycareersfuture.gov.sg/v2/search"
_CAP = 50
_SALARY_INTERVAL = {
    "monthly": "monthly",
    "annually": "yearly",
    "annual": "yearly",
    "yearly": "yearly",
    "hourly": "hourly",
    "daily": "daily",
    "weekly": "weekly",
}


class MyCareersFutureAdapter:
    id = "mycareersfuture"
    kind = "feed"
    full_board = False

    def fetch(self, scope: ScopeView, ctx: FetchContext) -> Iterator[FetchBatch]:
        search = _text(scope.params.get("search_term"))
        if search is None:
            raise RunPartial(self.id, "search_term is required")
        wanted = _cap(_int(scope.params.get("results_wanted"), _CAP))
        payload = read_json(
            ctx,
            self.id,
            "POST",
            _SEARCH,
            params={"limit": str(wanted), "page": "0"},
            json={"search": search, "sessionId": ""},
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
    title = _text(item.get("title"))
    metadata = as_dict(item.get("metadata"))
    source_url = _text(metadata.get("jobDetailsUrl"))
    company = as_dict(item.get("postedCompany"))
    if metadata.get("isHideHiringEmployerName") is True:
        return None
    company_name = _text(company.get("name"))
    job_id = _text(metadata.get("jobPostId")) or _text(item.get("uuid"))
    if not title or not source_url or not company_name or not job_id:
        return None
    hidden_salary = metadata.get("isHideSalary") is True
    salary = as_dict(item.get("salary"))
    interval = _salary_interval(salary.get("type"))
    levels = item.get("positionLevels") if isinstance(item.get("positionLevels"), list) else []
    level = levels[0].get("position") if levels and isinstance(levels[0], dict) else None
    return RawPosting(
        source_id="mycareersfuture",
        source_job_id=job_id,
        source_url=source_url,
        apply_url=source_url,
        company_name=company_name,
        title=title,
        location_raw=_place(item.get("address")),
        remote_hint=_remote(item.get("flexibleWorkArrangements")),
        posted_at=as_date(metadata.get("newPostingDate")),
        employment_type_raw=_employment(item.get("employmentTypes")),
        salary_min=as_decimal(salary.get("minimum")) if not hidden_salary else None,
        salary_max=as_decimal(salary.get("maximum")) if not hidden_salary else None,
        salary_currency="SGD" if not hidden_salary and salary.get("minimum") is not None else None,
        salary_interval_raw=interval if not hidden_salary else None,
        level_hint=_text(level),
        role_hint=_category(item.get("categories")),
        industry_hint=_category(item.get("categories")),
        payload=item,
    )


def _category(categories: Any) -> str | None:
    if not isinstance(categories, list):
        return None
    labels = [
        _text(item.get("category"))
        for item in categories
        if isinstance(item, dict) and _text(item.get("category"))
    ]
    present = [label for label in labels if label]
    return ", ".join(present) or None


def _place(address: Any) -> str:
    if not isinstance(address, dict):
        return "Singapore"
    if address.get("isOverseas") is True:
        country = _text(address.get("overseasCountry")) or "Singapore"
        foreign = _text(address.get("foreignAddress1"))
        return f"{foreign}, {country}" if foreign else country
    districts = address.get("districts") if isinstance(address.get("districts"), list) else []
    first = districts[0] if districts and isinstance(districts[0], dict) else {}
    district = first.get("location")
    name = _text(district)
    return f"{name}, Singapore" if name else "Singapore"


def _remote(arrangements: Any) -> str | None:
    if not isinstance(arrangements, list):
        return None
    for item in arrangements:
        if not isinstance(item, dict):
            continue
        label = (_text(item.get("flexibleWorkArrangement")) or "").lower()
        if "telecommuting" in label or "work from home" in label:
            return "remote"
    return None


def _employment(types: Any) -> str | None:
    if not isinstance(types, list):
        return None
    labels = [
        _text(item.get("employmentType"))
        for item in types
        if isinstance(item, dict) and _text(item.get("employmentType"))
    ]
    present = [label for label in labels if label]
    for label in present:
        lowered = label.lower()
        if "full" in lowered or "permanent" in lowered:
            return label
    return present[0] if present else None


def _salary_interval(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    kind = (_text(value.get("salaryType")) or "").lower()
    return _SALARY_INTERVAL.get(kind)


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
