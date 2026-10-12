"""facts.yaml: GLiNER thresholds. Parser choice lives in composition.py."""

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


def reload_config() -> None:
    load_config.cache_clear()
