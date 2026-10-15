"""Seniority inference. First matching rule wins."""

import re

Level = str

# Kept levels are everything else, including unknown (no level in the title).
EXCLUDED_LEVELS = frozenset({"manager", "principal", "junior", "intern"})

_RULES: tuple[tuple[str, str], ...] = (
    (r"\bintern\b", "intern"),
    (r"\b(?:junior|graduate|entry)\b", "junior"),
    (r"\bprincipal\b", "principal"),
    (r"\bstaff\b", "staff"),
    (r"\b(?:head of|director|manager)\b", "manager"),
    (r"\b(?:tech lead|lead)\b", "lead"),
    (r"\bsenior\b", "senior"),
)

_LINKEDIN = {
    "internship": "intern",
    "entry level": "junior",
    "associate": "junior",
    "mid-senior level": "senior",
    "director": "manager",
    "executive": "manager",
}


def infer_level(title: str, level_hint: str | None = None) -> Level:
    text = title.lower()
    for pattern, level in _RULES:
        if re.search(pattern, text):
            return level
    if level_hint:
        mapped = _LINKEDIN.get(level_hint.strip().lower())
        if mapped:
            return mapped
    return "unknown"
