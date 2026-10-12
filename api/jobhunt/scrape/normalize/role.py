"""Role and industry from a source hint, else title or company keywords."""

import re
from functools import cache

import yaml

from jobhunt.core.paths import config_path


def infer_role(title: str, hint: str | None = None) -> str | None:
    """Return a taxonomy slug. A hint wins when it matches; otherwise the title."""
    for text in (hint, title):
        found = _match(text, _role_keywords())
        if found:
            return found
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
def _role_keywords() -> list[tuple[str, str]]:
    return _keywords("roles.yaml")


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
