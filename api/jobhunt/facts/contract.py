"""Drop a parsed field that breaks a rule. The rule id is logged, not the text."""

from contextvars import ContextVar
from datetime import date, timedelta
from decimal import Decimal

import pycountry

from jobhunt.core.log import get_logger
from jobhunt.facts.base import LEVELS, JobDetail, LocationFact, PayFact, Place
from jobhunt.scrape.normalize.role import role_ids

log = get_logger("facts")

_recorded: ContextVar[list[tuple[str, str]] | None] = ContextVar("contract_drops", default=None)

_JOB_TYPES = {"fulltime", "parttime", "contract", "internship", "temporary"}
_WORKPLACES = {"onsite", "hybrid", "remote"}
_INTERVALS = {
    "yearly": "yearly",
    "year": "yearly",
    "annual": "yearly",
    "monthly": "monthly",
    "month": "monthly",
    "weekly": "weekly",
    "week": "weekly",
    "daily": "daily",
    "day": "daily",
    "hourly": "hourly",
    "hour": "hourly",
}
# A stated salary outside the band is not pay. The high end is deliberately wide.
_BANDS: dict[str, tuple[Decimal, Decimal]] = {
    "hourly": (Decimal("1"), Decimal("500")),
    "daily": (Decimal("10"), Decimal("5000")),
    "weekly": (Decimal("50"), Decimal("20000")),
    "monthly": (Decimal("100"), Decimal("100000")),
    "yearly": (Decimal("1000"), Decimal("2000000")),
}


def check_facts(
    detail: JobDetail,
    *,
    title: str,
    description: str,
    today: date | None = None,
    drops: list[tuple[str, str]] | None = None,
) -> JobDetail:
    """Return a copy with each failing field removed."""
    moment = today or date.today()
    text = f"{title}\n{description}"
    token = _recorded.set(drops)
    try:
        return _checked(detail, text, moment)
    finally:
        _recorded.reset(token)


def _checked(detail: JobDetail, text: str, moment: date) -> JobDetail:
    return JobDetail(
        pay=_keep(detail.pay, "pay", _pay_ok(detail.pay), text),
        job_type=_keep(detail.job_type, "job_type", _text_ok(detail.job_type, _JOB_TYPES), text),
        workplace=_keep(
            detail.workplace, "workplace", _text_ok(detail.workplace, _WORKPLACES), text
        ),
        locations=_locations(detail.locations, text),
        posted=_keep(detail.posted, "posted", _posted_ok(detail, moment), text),
        role=_keep(detail.role, "role", _text_ok(detail.role, role_ids()), text),
        level=_keep(detail.level, "level", _text_ok(detail.level, set(LEVELS)), text),
    )


def _locations(fact: LocationFact | None, text: str) -> LocationFact | None:
    if fact is None:
        return None
    if not _confidence_ok(fact.confidence):
        _drop("locations", "confidence")
        return None
    if not _evidence_ok(fact.parser_id, fact.evidence, text):
        _drop("locations", "evidence")
        return None
    places = [place for place in fact.value if _country_ok(place)]
    if len(places) != len(fact.value):
        _drop("locations", "country")
    if not places:
        return None
    if places == list(fact.value):
        return fact
    return fact.model_copy(update={"value": places})


def _keep[T](fact: T | None, field: str, rule: str | None, text: str) -> T | None:
    if fact is None:
        return None
    if rule is not None:
        _drop(field, rule)
        return None
    evidence = str(getattr(fact, "evidence", ""))
    parser_id = str(getattr(fact, "parser_id", ""))
    confidence = float(getattr(fact, "confidence", 0))
    if not _confidence_ok(confidence):
        _drop(field, "confidence")
        return None
    if not _evidence_ok(parser_id, evidence, text):
        _drop(field, "evidence")
        return None
    return fact


def _pay_ok(fact: PayFact | None) -> str | None:
    if fact is None:
        return None
    pay = fact.value
    interval = _INTERVALS.get((pay.interval or "").casefold())
    if interval is None or interval not in _BANDS:
        return "pay_interval"
    if pay.currency is None or pycountry.currencies.get(alpha_3=pay.currency.upper()) is None:
        return "pay_currency"
    low, high = _BANDS[interval]
    sides = [side for side in (pay.minimum, pay.maximum) if side is not None]
    if not sides or any(side <= 0 or side < low or side > high for side in sides):
        return "pay_band"
    if pay.minimum is not None and pay.maximum is not None and pay.minimum > pay.maximum:
        return "pay_order"
    return None


def _text_ok(fact: object, allowed: set[str]) -> str | None:
    if fact is None:
        return None
    value = str(getattr(fact, "value", ""))
    if value not in allowed:
        return "value"
    return None


def _posted_ok(detail: JobDetail, today: date) -> str | None:
    fact = detail.posted
    if fact is None:
        return None
    if fact.value > today:
        return "posted_future"
    if fact.value < today - timedelta(days=365):
        return "posted_old"
    return None


def _country_ok(place: Place) -> bool:
    if not place.country:
        return False
    return pycountry.countries.get(alpha_2=place.country.upper()) is not None


def _evidence_ok(parser_id: str, evidence: str, text: str) -> bool:
    if parser_id.startswith("api:"):
        return True
    return bool(evidence) and evidence in text


def _confidence_ok(confidence: float) -> bool:
    return 0 <= confidence <= 1


def _drop(field: str, rule: str) -> None:
    log.info("contract_drop field=%s rule=%s", field, rule)
    recorded = _recorded.get()
    if recorded is not None:
        recorded.append((field, rule))
