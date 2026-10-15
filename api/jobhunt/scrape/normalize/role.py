"""Role and industry from a source hint, else title or company keywords."""

import re
from functools import cache

import yaml

from jobhunt.core.paths import config_path

# Applied only after every other phrase misses, so "Web Developer (React)" stays frontend.
_FALLBACK_SLUGS = frozenset({"web_engineer"})
_LEVEL_WORD = (
    r"(?:senior|sr|staff|principal|junior|jr|intern|mid|associate|entry|graduate|"
    r"lead|level|[ivx]+|\d+)"
)
_BARE_SOFTWARE = re.compile(
    rf"^(?:{_LEVEL_WORD}\s+)*(?:engineers?|developers?)(?:\s+{_LEVEL_WORD})*$",
    re.IGNORECASE,
)


def infer_role(title: str, hint: str | None = None) -> str | None:
    """Return a taxonomy slug. A hint wins when it matches; otherwise the title."""
    primary = _primary_keywords()
    fallback = _fallback_keywords()
    for text in (hint, title):
        found = _match(text, primary)
        if found:
            return found
    for text in (hint, title):
        found = _match(text, fallback)
        if found:
            return found
    for text in (hint, title):
        if _bare_software(text):
            return "software"
    return None


def infer_industry(hint: str | None, company: str | None = None) -> str | None:
    """Return a taxonomy slug from the source industry, else the company name."""
    for text in (hint, company):
        found = _match(text, _industry_keywords())
        if found:
            return found
    return None


def role_ids() -> set[str]:
    return set(_taxonomy("roles.yaml"))


def industry_ids() -> set[str]:
    return set(_taxonomy("industries.yaml"))


def _match(text: str | None, keywords: list[tuple[str, str]]) -> str | None:
    if not text or not text.strip():
        return None
    lowered = text.lower()
    for phrase, slug in keywords:
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            return slug
    return None


@cache
def _primary_keywords() -> list[tuple[str, str]]:
    return [pair for pair in _keywords("roles.yaml") if pair[1] not in _FALLBACK_SLUGS]


@cache
def _fallback_keywords() -> list[tuple[str, str]]:
    return [pair for pair in _keywords("roles.yaml") if pair[1] in _FALLBACK_SLUGS]


def _bare_software(text: str | None) -> bool:
    """True when the title is only Engineer or Developer plus level words."""
    if not text or not text.strip():
        return False
    compact = re.sub(r"[^A-Za-z0-9]+", " ", text).strip()
    return _BARE_SOFTWARE.fullmatch(compact) is not None


@cache
def _industry_keywords() -> list[tuple[str, str]]:
    return _keywords("industries.yaml")


def _keywords(name: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for slug, phrases in _taxonomy(name).items():
        for phrase in phrases:
            pairs.append((phrase.lower(), slug))
    pairs.sort(key=lambda item: len(item[0]), reverse=True)
    return pairs


@cache
def _taxonomy(name: str) -> dict[str, list[str]]:
    raw = yaml.safe_load(config_path(name).read_text())
    if not isinstance(raw, dict):
        return {}
    taxonomy: dict[str, list[str]] = {}
    for slug, phrases in raw.items():
        if isinstance(phrases, list):
            taxonomy[str(slug)] = [str(phrase) for phrase in phrases]
    return taxonomy
