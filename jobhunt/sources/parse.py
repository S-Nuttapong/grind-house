"""Small parsers shared by source adapters."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast

from dateutil.parser import isoparse


def as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if value > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, tz=UTC).date()
    text = str(value).strip()
    if not text:
        return None
    parsed = cast(datetime, isoparse(text))
    return parsed.date()


def as_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def selected(company: Any, params: dict[str, Any]) -> bool:
    """ATS scopes select by company id list, or else by tier."""
    company_ids = params.get("company_ids")
    if company_ids:
        return int(company.id) in {int(item) for item in company_ids}
    tiers = params.get("tiers")
    if not tiers:
        return True
    return company.tier in set(tiers)
