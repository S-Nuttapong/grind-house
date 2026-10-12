"""JobSpy boards: Indeed, LinkedIn guest, Glassdoor, ZipRecruiter."""

import hashlib
import math
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from jobhunt.facts.base import JobDetail, Pay, PayFact, Place
from jobhunt.facts.mapping import (
    interval_word,
    location_fact,
    map_job_type,
    map_workplace,
    text,
    text_fact,
)
from jobhunt.facts.places import resolve_places
from jobhunt.scrape.sources.base import (
    FetchBatch,
    FetchContext,
    RawPosting,
    RunPartial,
    ScopeView,
    SourceDefaults,
    SourceSpec,
)
from jobhunt.scrape.sources.parse import as_date, as_decimal

_SITE = {
    "indeed": "indeed",
    "linkedin_guest": "linkedin",
    "glassdoor": "glassdoor",
    "ziprecruiter": "ziprecruiter",
    "naukri": "naukri",
}
_CAPS = {"linkedin_guest": 100, "naukri": 50}
_COUNTRY_REQUIRED = {"indeed", "glassdoor"}


_TWO_WEEKS = timedelta(days=14)
_SPECS = {
    "indeed": SourceSpec(
        kind="aggregator", min_interval=timedelta(minutes=15), close_after=_TWO_WEEKS
    ),
    "glassdoor": SourceSpec(
        kind="aggregator", min_interval=timedelta(minutes=15), close_after=_TWO_WEEKS
    ),
    "linkedin_guest": SourceSpec(
        kind="aggregator", min_interval=timedelta(minutes=15), close_after=_TWO_WEEKS
    ),
    "ziprecruiter": SourceSpec(
        kind="aggregator", min_interval=timedelta(hours=24), close_after=_TWO_WEEKS
    ),
    "naukri": SourceSpec(
        kind="aggregator", min_interval=timedelta(hours=24), close_after=_TWO_WEEKS
    ),
}


class JobSpySource(SourceDefaults):
    kind = "aggregator"
    full_board = False

    def __init__(self, source_id: str) -> None:
        if source_id not in _SITE:
            raise ValueError(f"no JobSpy site for {source_id}")
        self.id = source_id
        self.spec = _SPECS[source_id]

    def payload_facts(self, payload: dict[str, Any]) -> JobDetail:
        if self.id == "ziprecruiter":
            return JobDetail()
        return jobspy_facts(self.id, payload)

    def fetch(self, scope: ScopeView, ctx: FetchContext) -> Iterator[FetchBatch]:
        _ = ctx
        params = scope.params
        wanted = _cap(self.id, _int(params.get("results_wanted"), 50))
        try:
            rows = _scrape(self.id, params, wanted)
        except Exception as exc:
            text = str(exc)
            if "429" in text or "403" in text:
                from jobhunt.core.http import SourceBlocked

                raise SourceBlocked(self.id, 429 if "429" in text else 403) from exc
            raise RunPartial(self.id, text) from exc
        postings = [mapped for row in rows if (mapped := map_row(self.id, row)) is not None]
        yield FetchBatch(postings=postings)


def map_row(source_id: str, row: dict[str, Any]) -> RawPosting | None:
    title = _text(row.get("title"))
    source_url = _text(row.get("job_url"))
    company = _text(row.get("company"))
    if not title or not source_url or not company:
        return None
    job_id = _text(row.get("id")) or hashlib.sha256(source_url.encode()).hexdigest()
    remote = row.get("is_remote")
    remote_hint = "remote" if remote is True or _text(remote) == "True" else None
    if remote_hint is None:
        remote_hint = map_workplace(_text(row.get("work_from_home_type")))
    company_url = _text(row.get("company_url"))
    hint: dict[str, Any] = {}
    if company_url:
        hint["company_url"] = company_url
    return RawPosting(
        source_id=source_id,
        source_job_id=job_id,
        source_url=source_url,
        apply_url=_text(row.get("job_url_direct")) or source_url,
        company_name=company,
        company_hint=hint,
        title=title,
        location_raw=_text(row.get("location")),
        remote_hint=remote_hint,
        description_text=_text(row.get("description")),
        posted_at=_posted(row.get("date_posted")),
        employment_type_raw=_text(row.get("job_type")),
        salary_min=as_decimal(_number(row.get("min_amount"))),
        salary_max=as_decimal(_number(row.get("max_amount"))),
        salary_currency=_text(row.get("currency")),
        salary_interval_raw=_text(row.get("interval")),
        level_hint=_text(row.get("job_level")),
        role_hint=_text(row.get("job_function")),
        industry_hint=_text(row.get("company_industry")),
        payload={key: _jsonable(value) for key, value in row.items()},
    )


def _scrape(source_id: str, params: dict[str, Any], results_wanted: int) -> list[dict[str, Any]]:
    from jobspy import scrape_jobs

    frame = scrape_jobs(**_scrape_call(source_id, params, results_wanted))
    records = frame.to_dict(orient="records")
    return [dict(record) for record in records]


def _scrape_call(source_id: str, params: dict[str, Any], results_wanted: int) -> dict[str, Any]:
    """Arguments for ``scrape_jobs``. Indeed and Glassdoor must name their country.

    JobSpy's own default is ``usa``. Passing that when a scope forgot the country
    would store the wrong market, so the country is omitted unless the scope set it.
    """
    hours = params.get("hours_old")
    hours_old = int(hours) if isinstance(hours, (int, str)) and str(hours).strip() else None
    country = _text(params.get("country_indeed"))
    if source_id in _COUNTRY_REQUIRED and not country:
        raise ValueError(f"{source_id} scope requires country_indeed")
    call: dict[str, Any] = {
        "site_name": [_SITE[source_id]],
        "search_term": _text(params.get("search_term")),
        "location": _text(params.get("location")),
        "is_remote": bool(params.get("is_remote") or False),
        "hours_old": hours_old,
        "job_type": _text(params.get("job_type")),
        "results_wanted": results_wanted,
        "description_format": "markdown",
        "linkedin_fetch_description": source_id == "linkedin_guest" and results_wanted <= 50,
        "verbose": 0,
    }
    if country:
        call["country_indeed"] = country
    return call


def _cap(source_id: str, wanted: int) -> int:
    ceiling = _CAPS.get(source_id, 200)
    return max(1, min(wanted, ceiling))


def _int(value: Any, default: int) -> int:
    if value in (None, ""):
        return default
    return int(value)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def _number(value: Any) -> Any:
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _posted(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return as_date(_text(value))


def jobspy_facts(source_id: str, payload: dict[str, Any]) -> JobDetail:
    parser_id = f"api:{source_id}"
    origin = payload.get("salary_source")
    pay: PayFact | None = None
    low = as_decimal(payload.get("min_amount"))
    high = as_decimal(payload.get("max_amount"))
    currency = text(payload.get("currency"))
    if (low is not None or high is not None) and currency and origin != "description":
        pay = PayFact(
            value=Pay(
                minimum=low,
                maximum=high,
                currency=currency.upper(),
                interval=interval_word(text(payload.get("interval"))),
            ),
            confidence=1.0,
            evidence=f"{low}-{high} {currency}",
            parser_id=parser_id,
        )
    places: list[Place] = []
    location = text(payload.get("location"))
    if location:
        places.extend(resolve_places(location))
    addresses = payload.get("company_addresses")
    if isinstance(addresses, str) and not places:
        places.extend(resolve_places(addresses))
    return JobDetail(
        pay=pay,
        job_type=text_fact(
            map_job_type(text(payload.get("job_type"))),
            text(payload.get("job_type")),
            parser_id,
        ),
        workplace=text_fact(
            map_workplace(text(payload.get("work_from_home_type"))),
            text(payload.get("work_from_home_type")),
            parser_id,
        ),
        locations=location_fact(places, parser_id),
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
