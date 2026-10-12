"""Which boards cover which country, from config/markets.yaml."""

from functools import cache
from typing import Any

import yaml

from jobhunt.core.paths import config_path

# Adapter source ids that read a different key in the yaml.
_KEY = {"linkedin_guest": "linkedin"}


@cache
def load_markets() -> dict[str, dict[str, Any]]:
    raw = yaml.safe_load(config_path("markets.yaml").read_text())
    if not isinstance(raw, dict):
        return {}
    return {str(country): value for country, value in raw.items() if isinstance(value, dict)}


def board(country: str, source_id: str) -> dict[str, Any] | None:
    """Return that board's params for a country, or None when it has no feed there."""
    market = load_markets().get(country.upper())
    if market is None:
        return None
    entry = market.get(_KEY.get(source_id, source_id))
    if not isinstance(entry, dict):
        return None
    return entry


def location(country: str) -> str:
    market = load_markets().get(country.upper()) or {}
    value = market.get("location")
    return str(value) if value else country
