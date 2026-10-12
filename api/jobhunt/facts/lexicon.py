"""Phrase lists shared by the default parser. Data lives in config, not code."""

from functools import cache

import yaml

from jobhunt.core.paths import config_path


@cache
def _lexicon() -> dict[str, object]:
    loaded = yaml.safe_load(config_path("facts_lexicon.yaml").read_text())
    if not isinstance(loaded, dict):
        return {}
    return loaded


def phrases(group: str) -> dict[str, list[str]]:
    raw = _lexicon().get(group)
    if not isinstance(raw, dict):
        return {}
    result: dict[str, list[str]] = {}
    for key, values in raw.items():
        if isinstance(values, list):
            result[str(key)] = [str(item).casefold() for item in values]
    return result


def cues(name: str) -> list[str]:
    raw = _lexicon().get(name)
    if not isinstance(raw, list):
        return []
    return [str(item).casefold() for item in raw]


def reject_words() -> list[str]:
    return cues("salary_reject")
