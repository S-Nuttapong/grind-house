"""Geographic regions for the board filter. Timezone bands stay in regions.yaml."""

from functools import cache

import yaml

from jobhunt.core.paths import config_path


def region_ids() -> list[str]:
    return list(_table())


def countries_for(region: str) -> list[str]:
    return list(_table().get(region, ()))


@cache
def _table() -> dict[str, tuple[str, ...]]:
    raw = yaml.safe_load(config_path("geo_regions.yaml").read_text())
    if not isinstance(raw, dict):
        return {}
    table: dict[str, tuple[str, ...]] = {}
    for name, codes in raw.items():
        if isinstance(codes, list):
            table[str(name)] = tuple(str(code).upper() for code in codes)
    return table
