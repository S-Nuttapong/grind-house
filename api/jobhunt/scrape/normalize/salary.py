"""Salary annualization into USD."""

from decimal import Decimal
from typing import Any

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


def units_per_year(unit: str | None) -> Decimal | None:
    """CTS defaults: hourly 2080, daily 260, weekly 52, monthly 12, yearly 1."""
    canonical = _interval(unit)
    if canonical is None:
        return None
    return Decimal(_ANNUAL[canonical])


def save_base_pay(
    conn: Any,
    *,
    job_id: int,
    minimum: Decimal | int | float | None,
    maximum: Decimal | int | float | None,
    currency: str | None,
    unit: str | None,
    evidence: str | None,
    parser_id: str,
    replace_api: bool = False,
) -> None:
    """Insert the base row when the job has none.

    A board refresh may replace a row whose parser id starts with ``api:``.
    A parsed row is left in place.
    """
    low = _amount(minimum)
    high = _amount(maximum)
    if low is None and high is None:
        return
    if low is not None and high is not None and high < low:
        return
    code = currency.upper().strip() if currency else ""
    if len(code) != 3 or not code.isalpha():
        return
    canonical = _interval(unit)
    yearly = units_per_year(canonical)
    origin = parser_id.strip()
    if not origin:
        return
    text = (evidence or "").strip()
    if not origin.startswith("api:") and not text:
        return
    params = (job_id, canonical, code, low, high, yearly, text, origin, job_id)
    if replace_api:
        conn.execute(
            """
            INSERT INTO job_compensation (
              job_id, type, unit, currency, min_amount, max_amount,
              units_per_year, evidence, parser_id
            )
            VALUES (%s, 'base', %s, %s, %s, %s, %s, NULLIF(%s, ''), %s)
            ON CONFLICT (job_id) WHERE type = 'base'
            DO UPDATE SET
              unit = EXCLUDED.unit,
              currency = EXCLUDED.currency,
              min_amount = EXCLUDED.min_amount,
              max_amount = EXCLUDED.max_amount,
              units_per_year = EXCLUDED.units_per_year,
              evidence = EXCLUDED.evidence,
              parser_id = EXCLUDED.parser_id,
              updated_at = now()
            WHERE job_compensation.parser_id LIKE 'api:%%'
            """,
            params[:-1],
        )
        return
    conn.execute(
        """
        INSERT INTO job_compensation (
          job_id, type, unit, currency, min_amount, max_amount,
          units_per_year, evidence, parser_id
        )
        SELECT %s, 'base', %s, %s, %s, %s, %s, NULLIF(%s, ''), %s
        WHERE NOT EXISTS (
          SELECT 1 FROM job_compensation WHERE job_id = %s AND type = 'base'
        )
        """,
        params,
    )


def _amount(value: Decimal | int | float | None) -> Decimal | None:
    if value is None:
        return None
    amount = Decimal(str(value))
    if amount <= 0:
        return None
    return amount


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
