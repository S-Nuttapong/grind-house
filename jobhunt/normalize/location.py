"""Location parsing. Unknown stays unknown; a country is never guessed."""

import re
from pathlib import Path

import pycountry
import yaml

_REMOTE_WORDS = ("work from home", "remote", "anywhere", "wfh")
_STATE_CODES = {
    "al",
    "ak",
    "az",
    "ar",
    "ca",
    "co",
    "ct",
    "de",
    "fl",
    "ga",
    "hi",
    "id",
    "il",
    "in",
    "ia",
    "ks",
    "ky",
    "la",
    "me",
    "md",
    "ma",
    "mi",
    "mn",
    "ms",
    "mo",
    "mt",
    "ne",
    "nv",
    "nh",
    "nj",
    "nm",
    "ny",
    "nc",
    "nd",
    "oh",
    "ok",
    "or",
    "pa",
    "ri",
    "sc",
    "sd",
    "tn",
    "tx",
    "ut",
    "vt",
    "va",
    "wa",
    "wv",
    "wi",
    "wy",
    "dc",
}
_CITY_COUNTRY = {
    "bangkok": "TH",
    "singapore": "SG",
}
_COUNTRY_ALIASES = {
    "uk": "GB",
    "usa": "US",
    "us": "US",
    "united states": "US",
    "united kingdom": "GB",
}
_OFFSET = re.compile(r"\b(?:utc|gmt)\s*([+-])\s*(\d{1,2})\b", re.IGNORECASE)


def _regions() -> dict[str, tuple[int, int]]:
    path = _config("regions.yaml")
    raw = yaml.safe_load(path.read_text()) if path.exists() else {}
    return {str(name).lower(): (int(band[0]), int(band[1])) for name, band in raw.items()}


def _config(name: str) -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / name
        if candidate.exists():
            return candidate
    return Path("config") / name


def parse_location(
    raw: str | None,
    remote_hint: str | None = None,
) -> tuple[str | None, str | None, str, int | None, int | None]:
    text = " ".join(part for part in (raw, remote_hint) if part).strip()
    lowered = text.lower()
    remote = "unknown"
    if "hybrid" in lowered:
        remote = "hybrid"
    elif any(word in lowered for word in _REMOTE_WORDS):
        remote = "remote"

    tz_min, tz_max = _timezone(lowered)
    country = _country(lowered)
    city = _city(lowered, country)
    return country, city, remote, tz_min, tz_max


def _timezone(text: str) -> tuple[int | None, int | None]:
    match = _OFFSET.search(text)
    if match:
        sign = 1 if match.group(1) == "+" else -1
        offset = sign * int(match.group(2))
        return offset, offset
    for name, band in _regions().items():
        if re.search(rf"\b{re.escape(name)}\b", text):
            return band
    return None, None


def _country(text: str) -> str | None:
    for alias, code in _COUNTRY_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", text):
            return code
    for city, code in _CITY_COUNTRY.items():
        if re.search(rf"\b{re.escape(city)}\b", text):
            return code
    for country in pycountry.countries:
        name = country.name.lower()
        if re.search(rf"\b{re.escape(name)}\b", text):
            return str(country.alpha_2)
    parts = [part.strip() for part in re.split(r"[,/|]", text) if part.strip()]
    for part in parts:
        if part in _STATE_CODES:
            return "US"
    return None


def _city(text: str, country: str | None) -> str | None:
    for city in _CITY_COUNTRY:
        if re.search(rf"\b{re.escape(city)}\b", text):
            return city.title()
    if country == "SG" and "singapore" in text:
        return "Singapore"
    return None
