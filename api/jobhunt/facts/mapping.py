"""Shared conversions from a source payload into a JobDetail."""

from decimal import Decimal
from typing import Any

from jobhunt.facts.base import LocationFact, Place, TextFact
from jobhunt.scrape.sources.parse import as_decimal


def map_job_type(text: str | None) -> str | None:
    if not text:
        return None
    folded = "".join(char for char in text.casefold() if char.isalnum())
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


def location_fact(places: list[Place], parser_id: str) -> LocationFact | None:
    if not places:
        return None
    evidence = "; ".join(
        ", ".join(part for part in (place.city, place.region, place.country) if part)
        for place in places
    )
    return LocationFact(value=places, confidence=1.0, evidence=evidence, parser_id=parser_id)


def text_fact(value: str | None, evidence: str | None, parser_id: str) -> TextFact | None:
    if value is None or not evidence:
        return None
    return TextFact(value=value, confidence=1.0, evidence=evidence, parser_id=parser_id)


def text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def flat(value: object) -> str | None:
    if isinstance(value, str):
        return text(value)
    if isinstance(value, list) and value and isinstance(value[0], str):
        return text(value[0])
    if isinstance(value, dict):
        return text(value.get("name") or value.get("value"))
    return None


def interval_word(text_value: str | None) -> str | None:
    if text_value is None:
        return None
    folded = text_value.casefold()
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


def metadata(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("metadata")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def decimal_named(meta: list[dict[str, Any]], name: str) -> Decimal | None:
    for item in meta:
        if str(item.get("name") or "").casefold() == name:
            return as_decimal(item.get("value"))
    return None
