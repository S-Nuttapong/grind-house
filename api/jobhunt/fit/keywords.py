"""Matched and missing terms, from the canonical vocabulary in synonyms.yaml."""

import re
from functools import cache
from typing import Any

import yaml

from jobhunt.core.paths import config_path

_CONFIG = config_path("synonyms.yaml")


@cache
def _entries() -> dict[str, Any]:
    return yaml.safe_load(_CONFIG.read_text()) or {}


@cache
def vocabulary() -> dict[str, tuple[str, ...]]:
    """Map each canonical term to the forms that count as that term."""
    vocab: dict[str, tuple[str, ...]] = {}
    for term, spec in _entries().items():
        forms = [str(term), *[str(item) for item in spec.get("syn", [])]]
        vocab[str(term)] = tuple(forms)
    return vocab


@cache
def _stack_terms() -> frozenset[str]:
    return frozenset(str(term) for term, spec in _entries().items() if spec.get("kind") == "stack")


def terms_in(text: str) -> set[str]:
    folded = text.lower()
    found: set[str] = set()
    for term, forms in vocabulary().items():
        if any(re.search(rf"(?<!\w){re.escape(form.lower())}(?!\w)", folded) for form in forms):
            found.add(term)
    return found


def stack_terms_in(text: str) -> set[str]:
    """Named technologies (kind: stack) in the text."""
    return terms_in(text) & _stack_terms()


def compare(profile_text: str, job_description: str) -> tuple[list[str], list[str]]:
    """Return (matched, missing), both sorted. Missing terms are in the job only."""
    profile_terms = terms_in(profile_text)
    job_terms = terms_in(job_description)
    return sorted(profile_terms & job_terms), sorted(job_terms - profile_terms)
