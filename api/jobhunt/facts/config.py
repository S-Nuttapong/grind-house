"""facts.yaml: which parser runs for each field, and GLiNER thresholds."""

from functools import cache

import yaml

from jobhunt.core.paths import config_path
from jobhunt.facts.base import FIELDS, FieldName


@cache
def load_config() -> dict[str, object]:
    loaded = yaml.safe_load(config_path("facts.yaml").read_text())
    if not isinstance(loaded, dict):
        return {}
    return loaded


def chains() -> dict[FieldName, list[str]]:
    raw = load_config().get("chains")
    if not isinstance(raw, dict):
        return {field: ["api", "default"] for field in FIELDS}
    result: dict[FieldName, list[str]] = {}
    for field in FIELDS:
        order = raw.get(field)
        if isinstance(order, list) and all(isinstance(item, str) for item in order):
            result[field] = [str(item) for item in order]
        else:
            result[field] = ["api", "default"]
    return result


def gliner_thresholds() -> dict[FieldName, float]:
    raw = load_config().get("gliner")
    result: dict[FieldName, float] = {field: 0.5 for field in FIELDS}
    if not isinstance(raw, dict):
        return result
    for field in FIELDS:
        value = raw.get(field)
        if isinstance(value, (int, float)):
            result[field] = float(value)
    return result


def gliner_enabled() -> bool:
    return any("gliner" in order for order in chains().values())


def reload_config() -> None:
    load_config.cache_clear()
