"""Structured fields already on a source payload. These are the silver labels."""

from decimal import Decimal
from typing import Any

from jobhunt.facts.base import JobDetail, LocationFact, Pay, PayFact, Place, TextFact
from jobhunt.facts.places import resolve_places
from jobhunt.scrape.sources.parse import as_decimal

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


def from_payload(source_id: str, payload: dict[str, Any]) -> JobDetail:
    """Map one source payload into a JobDetail. Unknown fields stay empty."""
    if source_id == "greenhouse":
        return _greenhouse(payload)
    if source_id == "lever":
        return _lever(payload)
    if source_id == "ashby":
        return _ashby(payload)
    if source_id in {"indeed", "linkedin_guest", "glassdoor", "naukri"}:
        return _jobspy(source_id, payload)
    if source_id == "seek":
        return _seek(payload)
    return JobDetail()


def augment_text(source_id: str, payload: dict[str, Any], description: str) -> str:
    """Append a structured salary line the description itself does not carry."""
    if source_id != "seek":
        return description
    label = payload.get("salary")
    if not isinstance(label, str) or not label.strip():
        return description
    return f"{description}\nSalary: {label.strip()}\n"


def _greenhouse(payload: dict[str, Any]) -> JobDetail:
    meta = _metadata(payload)
    places = _offices(payload)
    raw_name = _location_name(payload)
    placeholder = raw_name is not None and raw_name.casefold() in _PLACEHOLDERS
    workplace = _workplace_text(raw_name) if placeholder else None
    if raw_name and raw_name.casefold() not in _PLACEHOLDERS:
        for place in resolve_places(raw_name):
            if place not in places:
                places.append(place)
    type_text = _named(meta, _TYPE_NAMES)
    work_text = _named(meta, _WORK_NAMES)
    return JobDetail(
        pay=_pay_from_metadata(meta),
        job_type=_text_fact(map_job_type(type_text), type_text, "api:greenhouse"),
        workplace=_text_fact(
            map_workplace(work_text) or workplace,
            work_text or raw_name,
            "api:greenhouse",
        ),
        locations=_location_fact(places, "api:greenhouse"),
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
    low = _decimal_named(meta, "minimum salary")
    high = _decimal_named(meta, "maximum salary")
    if low is None and high is None:
        return None
    return PayFact(
        value=Pay(minimum=low, maximum=high, currency="USD", interval="yearly"),
        confidence=1.0,
        evidence=f"{low}-{high}",
        parser_id="api:greenhouse",
    )


def _lever(payload: dict[str, Any]) -> JobDetail:
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
    pay = _lever_pay(payload.get("salaryRange"))
    return JobDetail(
        pay=pay,
        job_type=_text_fact(
            map_job_type(commitment if isinstance(commitment, str) else None),
            commitment if isinstance(commitment, str) else None,
            "api:lever",
        ),
        workplace=_text_fact(
            map_workplace(_text(payload.get("workplaceType"))),
            _text(payload.get("workplaceType")),
            "api:lever",
        ),
        locations=_location_fact(places, "api:lever"),
    )


def _lever_pay(raw: object) -> PayFact | None:
    if not isinstance(raw, dict):
        return None
    low = as_decimal(raw.get("min"))
    high = as_decimal(raw.get("max"))
    currency = _text(raw.get("currency"))
    if low is None and high is None or currency is None:
        return None
    return PayFact(
        value=Pay(
            minimum=low,
            maximum=high,
            currency=currency.upper(),
            interval=_lever_interval(_text(raw.get("interval"))),
        ),
        confidence=1.0,
        evidence=str(raw),
        parser_id="api:lever",
    )


def _ashby(payload: dict[str, Any]) -> JobDetail:
    places: list[Place] = []
    for key in ("location",):
        raw = payload.get(key)
        if isinstance(raw, str):
            places.extend(place for place in resolve_places(raw) if place not in places)
    secondary = payload.get("secondaryLocations")
    if isinstance(secondary, list):
        for item in secondary:
            raw = item.get("location") if isinstance(item, dict) else item
            if isinstance(raw, str):
                places.extend(place for place in resolve_places(raw) if place not in places)
    address = payload.get("address")
    postal = address.get("postalAddress") if isinstance(address, dict) else None
    if isinstance(postal, dict):
        locality = _text(postal.get("addressLocality"))
        country = _text(postal.get("addressCountry"))
        text = ", ".join(part for part in (locality, country) if part)
        if text:
            places.extend(place for place in resolve_places(text) if place not in places)
    workplace = _text(payload.get("workplaceType"))
    if workplace is None and payload.get("isRemote") is True:
        workplace = "remote"
    return JobDetail(
        pay=_ashby_pay(payload.get("compensation")),
        job_type=_text_fact(
            map_job_type(_text(payload.get("employmentType"))),
            _text(payload.get("employmentType")),
            "api:ashby",
        ),
        workplace=_text_fact(map_workplace(workplace), workplace, "api:ashby"),
        locations=_location_fact(places, "api:ashby"),
    )


def _ashby_pay(compensation: object) -> PayFact | None:
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
        currency = _text(component.get("currencyCode"))
        if low is None and high is None or currency is None:
            continue
        interval = str(component.get("interval") or "").upper()
        return PayFact(
            value=Pay(
                minimum=low,
                maximum=high,
                currency=currency.upper(),
                interval=_ashby_interval(interval),
            ),
            confidence=1.0,
            evidence=str(component),
            parser_id="api:ashby",
        )
    return None


def _jobspy(source_id: str, payload: dict[str, Any]) -> JobDetail:
    parser_id = f"api:{source_id}"
    origin = payload.get("salary_source")
    pay: PayFact | None = None
    low = as_decimal(payload.get("min_amount"))
    high = as_decimal(payload.get("max_amount"))
    currency = _text(payload.get("currency"))
    if (low is not None or high is not None) and currency and origin != "description":
        pay = PayFact(
            value=Pay(
                minimum=low,
                maximum=high,
                currency=currency.upper(),
                interval=_canonical(_text(payload.get("interval"))),
            ),
            confidence=1.0,
            evidence=f"{low}-{high} {currency}",
            parser_id=parser_id,
        )
    places: list[Place] = []
    location = _text(payload.get("location"))
    if location:
        places.extend(resolve_places(location))
    addresses = payload.get("company_addresses")
    if isinstance(addresses, str) and not places:
        places.extend(resolve_places(addresses))
    return JobDetail(
        pay=pay,
        job_type=_text_fact(
            map_job_type(_text(payload.get("job_type"))),
            _text(payload.get("job_type")),
            parser_id,
        ),
        workplace=_text_fact(
            map_workplace(_text(payload.get("work_from_home_type"))),
            _text(payload.get("work_from_home_type")),
            parser_id,
        ),
        locations=_location_fact(places, parser_id),
    )


def _seek(payload: dict[str, Any]) -> JobDetail:
    country = _text(payload.get("country"))
    if country is None or len(country) != 2:
        return JobDetail()
    return JobDetail(locations=_location_fact([Place(country=country.upper())], "api:seek"))


def map_job_type(text: str | None) -> str | None:
    if not text:
        return None
    folded = re_collapse(text)
    if "intern" in folded:
        return "internship"
    if "parttime" in folded:
        return "parttime"
    if "tempor" in folded:
        return "temporary"
    if "contract" in folded:
        return "contract"
    if "fulltime" in folded or "permanent" in folded:
        return "fulltime"
    return None


def map_workplace(text: str | None) -> str | None:
    if not text:
        return None
    folded = text.casefold()
    if "hybrid" in folded:
        return "hybrid"
    if "remote" in folded or "work from home" in folded or folded.strip() == "wfh":
        return "remote"
    if "on-site" in folded or "onsite" in folded or "in-office" in folded or "in office" in folded:
        return "onsite"
    return None


def re_collapse(text: str) -> str:
    return "".join(char for char in text.casefold() if char.isalnum())


def _metadata(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("metadata")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _named(meta: list[dict[str, Any]], names: set[str]) -> str | None:
    for item in meta:
        if str(item.get("name") or "").casefold() in names:
            return _flat(item.get("value"))
    return None


def _decimal_named(meta: list[dict[str, Any]], name: str) -> Decimal | None:
    for item in meta:
        if str(item.get("name") or "").casefold() == name:
            return as_decimal(item.get("value"))
    return None


def _currency_range(value: object) -> Pay | None:
    if not isinstance(value, dict):
        return None
    low = as_decimal(value.get("min_value"))
    high = as_decimal(value.get("max_value"))
    currency = _text(value.get("unit"))
    if currency is None or (low is None and high is None):
        return None
    return Pay(minimum=low, maximum=high, currency=currency.upper(), interval="yearly")


def _location_name(payload: dict[str, Any]) -> str | None:
    location = payload.get("location")
    if isinstance(location, dict):
        return _text(location.get("name"))
    return None


def _workplace_text(text: str | None) -> str | None:
    return map_workplace(text)


def _location_fact(places: list[Place], parser_id: str) -> LocationFact | None:
    if not places:
        return None
    evidence = "; ".join(
        ", ".join(part for part in (place.city, place.region, place.country) if part)
        for place in places
    )
    return LocationFact(value=places, confidence=1.0, evidence=evidence, parser_id=parser_id)


def _text_fact(value: str | None, evidence: str | None, parser_id: str) -> TextFact | None:
    if value is None or not evidence:
        return None
    return TextFact(value=value, confidence=1.0, evidence=evidence, parser_id=parser_id)


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _flat(value: object) -> str | None:
    if isinstance(value, str):
        return _text(value)
    if isinstance(value, list) and value and isinstance(value[0], str):
        return _text(value[0])
    if isinstance(value, dict):
        return _text(value.get("name") or value.get("value"))
    return None


def _lever_interval(text: str | None) -> str | None:
    if text is None:
        return None
    folded = text.casefold()
    for word, interval in (
        ("year", "yearly"),
        ("month", "monthly"),
        ("week", "weekly"),
        ("day", "daily"),
        ("hour", "hourly"),
    ):
        if word in folded:
            return interval
    return None


def _ashby_interval(text: str) -> str | None:
    if "YEAR" in text:
        return "yearly"
    if "MONTH" in text:
        return "monthly"
    if "WEEK" in text:
        return "weekly"
    if "DAY" in text:
        return "daily"
    if "HOUR" in text:
        return "hourly"
    return None


def _canonical(text: str | None) -> str | None:
    if text is None:
        return None
    folded = text.casefold()
    for word, interval in (
        ("year", "yearly"),
        ("month", "monthly"),
        ("week", "weekly"),
        ("day", "daily"),
        ("hour", "hourly"),
    ):
        if word in folded:
            return interval
    return None
