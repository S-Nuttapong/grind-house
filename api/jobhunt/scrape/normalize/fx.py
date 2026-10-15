"""Daily FX rates. Frankfurter first, open.er-api only for currencies it lacks."""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from jobhunt.core.log import get_logger

log = get_logger("fx")

_FRANKFURTER = "https://api.frankfurter.dev/v1/latest?base=USD"
_OPEN_ER = "https://open.er-api.com/v6/latest/USD"
_MAX_AGE = timedelta(hours=24)

# Currencies this board has stored, plus USD. A code neither API quotes is skipped.
_WATCH = (
    "USD",
    "AUD",
    "CAD",
    "CHF",
    "EUR",
    "GBP",
    "HKD",
    "IDR",
    "INR",
    "JPY",
    "MYR",
    "NZD",
    "PHP",
    "SGD",
    "THB",
    "VND",
)


def fx_is_due(conn: Any, *, now: datetime | None = None) -> bool:
    """True when the newest fetch is missing or older than a day."""
    current = now or datetime.now(UTC)
    row = conn.execute("SELECT max(fetched_at) FROM fx_rates").fetchone()
    latest = None if row is None else row[0]
    if not isinstance(latest, datetime):
        return True
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=UTC)
    return current - latest >= _MAX_AGE


def refresh_fx(
    conn: Any,
    *,
    now: datetime | None = None,
    get: Callable[[str], dict[str, Any]] | None = None,
) -> int:
    """Upsert rates when they are stale. Returns the number of rows written."""
    if not fx_is_due(conn, now=now):
        return 0
    return sync_fx(conn, get=get)


def sync_fx(conn: Any, *, get: Callable[[str], dict[str, Any]] | None = None) -> int:
    """Fetch and upsert. On a bad response, leave the stored rates in place."""
    fetch = get or _get_json
    try:
        primary = fetch(_FRANKFURTER)
        secondary = fetch(_OPEN_ER)
        rows = _rows(primary, secondary, _wanted(conn))
    except (httpx.HTTPError, ValueError, KeyError, InvalidOperation) as exc:
        log.warning("fx sync failed: %s", exc)
        return 0
    for currency, usd_per_unit, as_of, source in rows:
        conn.execute(
            """
            INSERT INTO fx_rates (currency, usd_per_unit, as_of, source, fetched_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (currency) DO UPDATE
            SET usd_per_unit = EXCLUDED.usd_per_unit,
                as_of = EXCLUDED.as_of,
                source = EXCLUDED.source,
                fetched_at = now()
            """,
            (currency, usd_per_unit, as_of, source),
        )
    return len(rows)


def _wanted(conn: Any) -> set[str]:
    codes = set(_WATCH)
    rows = conn.execute("SELECT DISTINCT currency FROM job_compensation").fetchall()
    codes.update(str(row[0]) for row in rows)
    return codes


def _rows(
    primary: dict[str, Any], secondary: dict[str, Any], wanted: set[str]
) -> list[tuple[str, Decimal, date, str]]:
    frankfurter_date = date.fromisoformat(str(primary["date"]))
    frankfurter = {str(code): Decimal(str(rate)) for code, rate in dict(primary["rates"]).items()}
    if secondary.get("result") != "success":
        raise ValueError("open.er-api did not succeed")
    updated = _er_date(str(secondary["time_last_update_utc"]))
    fallback = {str(code): Decimal(str(rate)) for code, rate in dict(secondary["rates"]).items()}
    rows: list[tuple[str, Decimal, date, str]] = []
    for code in sorted(wanted):
        if code == "USD":
            rows.append(("USD", Decimal(1), frankfurter_date, "frankfurter"))
            continue
        if code in frankfurter:
            rows.append((code, _usd_per(frankfurter[code]), frankfurter_date, "frankfurter"))
        elif code in fallback:
            rows.append((code, _usd_per(fallback[code]), updated, "open_er_api"))
    return rows


def _usd_per(units_per_usd: Decimal) -> Decimal:
    if units_per_usd <= 0:
        raise ValueError("fx rate must be positive")
    return Decimal(1) / units_per_usd


def _er_date(text: str) -> date:
    parsed = datetime.strptime(text, "%a, %d %b %Y %H:%M:%S %z")
    return parsed.date()


def _get_json(url: str) -> dict[str, Any]:
    response = httpx.get(url, timeout=20)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("fx payload was not an object")
    return body
