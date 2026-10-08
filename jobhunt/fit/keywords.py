"""Matched and missing terms, from the canonical vocabulary in synonyms.yaml."""

import re
from functools import cache
from pathlib import Path

import yaml

_CONFIG = Path(__file__).resolve().parents[2] / "config" / "synonyms.yaml"


@cache
def vocabulary() -> dict[str, tuple[str, ...]]:
    """Map each canonical term to the forms that count as that term."""
    raw = yaml.safe_load(_CONFIG.read_text()) or {}
    vocab: dict[str, tuple[str, ...]] = {}
    for term, spec in raw.items():
        forms = [str(term), *[str(item) for item in spec.get("syn", [])]]
        vocab[str(term)] = tuple(forms)
    return vocab


def terms_in(text: str) -> set[str]:
    folded = text.lower()
    found: set[str] = set()
    for term, forms in vocabulary().items():
        if any(re.search(rf"(?<!\w){re.escape(form.lower())}(?!\w)", folded) for form in forms):
            found.add(term)
    return found


def compare(profile_text: str, job_description: str) -> tuple[list[str], list[str]]:
    """Return (matched, missing), both sorted. Missing terms are in the job only."""
    profile_terms = terms_in(profile_text)
    job_terms = terms_in(job_description)
    return sorted(profile_terms & job_terms), sorted(job_terms - profile_terms)
