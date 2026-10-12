"""Salary annualization into USD."""

from decimal import Decimal

import yaml

from jobhunt.core.paths import config_path

_ANNUAL = {
    "yearly": 1,
    "year": 1,
    "annual": 1,
    "monthly": 12,
    "month": 12,
    "weekly": 52,
    "week": 52,
    "daily": 260,
    "day": 260,
    "hourly": 2080,
    "hour": 2080,
}


def _rates() -> dict[str, Decimal]:
    raw = yaml.safe_load(config_path("fx.yaml").read_text())
    table = raw.get("to_usd") or {}
    return {str(code).upper(): Decimal(str(rate)) for code, rate in table.items()}


def normalize_salary(
    minimum: Decimal | int | float | None,
    maximum: Decimal | int | float | None,
    currency: str | None,
    interval: str | None,
) -> tuple[Decimal | None, Decimal | None, str | None, str | None, Decimal | None]:
    """Return min, max, currency, canonical interval, and usd_year_min."""
    canonical = _interval(interval)
    low = Decimal(str(minimum)) if minimum is not None else None
    high = Decimal(str(maximum)) if maximum is not None else None
    code = currency.upper() if currency else None
    usd = _usd_year(low if low is not None else high, code, canonical)
    return low, high, code, canonical, usd


def _interval(interval: str | None) -> str | None:
    if interval is None:
        return None
    key = interval.strip().lower()
    if key in {"yearly", "year", "annual"}:
        return "yearly"
    if key in {"monthly", "month"}:
        return "monthly"
    if key in {"weekly", "week"}:
        return "weekly"
    if key in {"daily", "day"}:
        return "daily"
    if key in {"hourly", "hour"}:
        return "hourly"
    return None


def _usd_year(amount: Decimal | None, currency: str | None, interval: str | None) -> Decimal | None:
    if amount is None or currency is None or interval is None:
        return None
    factor = _ANNUAL.get(interval)
    rate = _rates().get(currency)
    if factor is None or rate is None:
        return None
    return (amount * Decimal(factor) * rate).quantize(Decimal("1"))
