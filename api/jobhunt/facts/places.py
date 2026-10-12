"""Resolve place strings against GeoNames and pycountry. Unknown stays unknown."""

import re
from functools import cache

import pycountry

from jobhunt.facts.base import Place

_SKIP = {
    "remote",
    "hybrid",
    "onsite",
    "on-site",
    "anywhere",
    "distributed",
    "worldwide",
    "n/a",
    "na",
    "multiple locations",
    "in-office",
    "in office",
}
_EXTRA_COUNTRIES = {
    "uk": "GB",
    "u.k.": "GB",
    "great britain": "GB",
    "usa": "US",
    "u.s.": "US",
    "u.s.a.": "US",
    "us": "US",
    "uae": "AE",
    "south korea": "KR",
    "korea": "KR",
    "vietnam": "VN",
    "taiwan": "TW",
    "russia": "RU",
    "czechia": "CZ",
    "turkey": "TR",
    "holland": "NL",
}
_SPLIT = re.compile(r"\s+(?:or|and)\s+|[,;/|]", re.IGNORECASE)


class _City:
    __slots__ = ("country", "name", "population")

    def __init__(self, name: str, country: str, population: int) -> None:
        self.name = name
        self.country = country
        self.population = population


@cache
def _cities() -> dict[str, list[_City]]:
    from geonamescache import GeonamesCache

    index: dict[str, list[_City]] = {}
    for record in GeonamesCache(min_city_population=15000).get_cities().values():
        name = str(record.get("name") or "")
        country = str(record.get("countrycode") or "")
        if not name or len(country) != 2:
            continue
        city = _City(name, country, int(record.get("population") or 0))
        keys = {name.casefold()}
        alternates = record.get("alternatenames") or []
        if isinstance(alternates, list):
            keys.update(str(item).casefold() for item in alternates if isinstance(item, str))
        for key in keys:
            if len(key) < 3:
                continue
            index.setdefault(key, []).append(city)
    return index


@cache
def _country_names() -> list[tuple[str, str]]:
    names: dict[str, str] = dict(_EXTRA_COUNTRIES)
    for country in pycountry.countries:
        code = str(country.alpha_2)
        for attr in ("name", "common_name", "official_name"):
            value = getattr(country, attr, None)
            if isinstance(value, str) and value.strip():
                names.setdefault(value.casefold(), code)
    return sorted(names.items(), key=lambda item: len(item[0]), reverse=True)


@cache
def _regions() -> dict[str, tuple[str, str]]:
    """Lowercased subdivision name or code to (country, region name)."""
    found: dict[str, tuple[str, str]] = {}
    for subdivision in pycountry.subdivisions:
        country = str(subdivision.country_code)
        name = str(subdivision.name)
        found.setdefault(name.casefold(), (country, name))
        code = str(subdivision.code)
        short = code.split("-")[-1]
        if len(short) == 2 and short.isalpha():
            key = short.casefold()
            # US state codes win over an earlier country that shares the letters.
            if key not in found or country == "US":
                found[key] = (country, name)
    return found


def resolve_places(text: str, country_hint: str | None = None) -> list[Place]:
    """Places named in a short location string. Empty when nothing resolves."""
    cleaned = re.sub(r"\([^)]*\)", " ", text).strip()
    if not cleaned or cleaned.casefold() in _SKIP:
        return []
    pieces = [piece.strip(" .") for piece in _SPLIT.split(cleaned) if piece.strip(" .")]
    if len(pieces) <= 1:
        pieces = [cleaned]
    found: list[Place] = []
    hinted = country_hint.upper() if country_hint and len(country_hint) == 2 else None
    for piece in pieces:
        place = _one(piece, hinted)
        if place is not None and place not in found:
            found.append(place)
    return found


def _one(piece: str, country_hint: str | None) -> Place | None:
    if not piece or piece.casefold() in _SKIP or len(piece) > 80:
        return None
    country = _country_in(piece) or country_hint
    region = _region_in(piece, country)
    if region is not None and country is None:
        country = region[0]
    city = _city_in(piece, country)
    if city is None and region is None and _country_in(piece) is None:
        return None
    code = city.country if city is not None else country
    if code is None and region is not None:
        code = region[0]
    return Place(
        city=None if city is None else city.name,
        region=None if region is None else region[1],
        country=code,
    )


def _country_in(text: str) -> str | None:
    folded = text.casefold()
    for name, code in _country_names():
        if re.search(rf"\b{re.escape(name)}\b", folded):
            return code
    return None


def _region_in(text: str, country: str | None) -> tuple[str, str] | None:
    regions = _regions()
    for token in re.split(r"\s+", text.strip()):
        hit = regions.get(token.casefold())
        if hit is None:
            continue
        if country is not None and hit[0] != country:
            continue
        if len(token) == 2 and country not in (None, "US", "CA", "AU"):
            continue
        return hit
    folded = text.casefold()
    for name, hit in regions.items():
        if len(name) < 4:
            continue
        if country is not None and hit[0] != country:
            continue
        if re.search(rf"\b{re.escape(name)}\b", folded):
            return hit
    return None


def _city_in(text: str, country: str | None) -> _City | None:
    folded = text.casefold().strip()
    if folded in _SKIP:
        return None
    hits = list(_cities().get(folded, []))
    if country is not None:
        hits = [city for city in hits if city.country == country]
    if not hits:
        return None
    hits.sort(key=lambda city: city.population, reverse=True)
    if country is None:
        countries = {city.country for city in hits}
        if len(countries) > 1:
            best = hits[0]
            second = max(city.population for city in hits if city.country != best.country)
            if best.population < 10 * max(second, 1):
                return None
    return hits[0]
