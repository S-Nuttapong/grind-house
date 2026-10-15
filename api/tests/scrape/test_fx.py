"""FX sync prefers Frankfurter and does not wipe rates when a provider fails."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from jobhunt.scrape.normalize.fx import fx_is_due, refresh_fx, sync_fx

_PRIMARY = {
    "date": "2026-10-15",
    "rates": {"THB": "33.575", "EUR": "0.89"},
}
_SECONDARY = {
    "result": "success",
    "time_last_update_utc": "Thu, 15 Oct 2026 00:02:31 +0000",
    "rates": {"THB": "33.6", "VND": "25890.2"},
}


def test_frankfurter_wins_and_the_other_api_fills_vnd(conn) -> None:
    conn.execute("DELETE FROM fx_rates")
    count = sync_fx(conn, get=_ok)
    assert count >= 3
    thb = conn.execute(
        "SELECT source, usd_per_unit FROM fx_rates WHERE currency = 'THB'"
    ).fetchone()
    vnd = conn.execute(
        "SELECT source, usd_per_unit FROM fx_rates WHERE currency = 'VND'"
    ).fetchone()
    assert thb is not None and thb[0] == "frankfurter"
    assert thb[1] == Decimal(1) / Decimal("33.575")
    assert vnd is not None and vnd[0] == "open_er_api"
    assert vnd[1] == Decimal(1) / Decimal("25890.2")


def test_a_failed_fetch_keeps_the_stored_rate(conn) -> None:
    before = conn.execute("SELECT usd_per_unit FROM fx_rates WHERE currency = 'THB'").fetchone()

    def _fail(url: str) -> dict[str, object]:
        raise httpx.ConnectError("down")

    assert sync_fx(conn, get=_fail) == 0
    after = conn.execute("SELECT usd_per_unit FROM fx_rates WHERE currency = 'THB'").fetchone()
    assert after == before


def test_refresh_skips_a_fetch_from_the_last_day(conn) -> None:
    calls: list[str] = []

    def _get(url: str) -> dict[str, object]:
        calls.append(url)
        return _ok(url)

    assert refresh_fx(conn, get=_get) == 0
    assert calls == []
    latest = conn.execute("SELECT max(fetched_at) FROM fx_rates").fetchone()
    assert latest is not None and latest[0] is not None
    later = latest[0] + timedelta(hours=25)
    assert fx_is_due(conn, now=later)
    assert refresh_fx(conn, now=later, get=_get) > 0
    assert calls


def test_a_fresh_rate_is_not_due(conn) -> None:
    assert fx_is_due(conn, now=datetime.now(UTC)) is False
    assert fx_is_due(conn, now=datetime.now(UTC) + timedelta(hours=24)) is True


def _ok(url: str) -> dict[str, object]:
    if "frankfurter" in url:
        return _PRIMARY
    if "er-api" in url:
        return _SECONDARY
    raise AssertionError(url)
