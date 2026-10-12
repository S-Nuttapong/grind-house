"""Maps a parser name to its factory."""

import os
from collections.abc import Callable

from jobhunt.facts.base import JobDetailParser
from jobhunt.facts.chain import ChainParser
from jobhunt.facts.config import chains
from jobhunt.facts.default import DefaultParser

_FACTORIES: dict[str, Callable[[], JobDetailParser]] = {
    "default": DefaultParser,
}


def register(name: str, factory: Callable[[], JobDetailParser]) -> None:
    _FACTORIES[name] = factory


def names() -> list[str]:
    return sorted(_FACTORIES)


def create(name: str) -> JobDetailParser:
    if name == "gliner" and "gliner" not in _FACTORIES:
        from jobhunt.facts.gliner import GlinerParser

        _FACTORIES["gliner"] = GlinerParser
    factory = _FACTORIES.get(name)
    if factory is None:
        known = ", ".join(names())
        raise ValueError(f"unknown facts parser {name!r}; known: {known}")
    parser = factory()
    if parser.sends_data_offsite and os.environ.get("FACTS_ALLOW_OFFSITE") != "1":
        raise ValueError(
            f"{name} sends job text off this machine; set FACTS_ALLOW_OFFSITE=1 to load it"
        )
    return parser


def chain_from_config() -> ChainParser:
    """Text parsers named in facts.yaml, skipping the api step (it is not text)."""
    order = chains()
    wanted: list[str] = []
    for field_order in order.values():
        for name in field_order:
            if name != "api" and name not in wanted:
                wanted.append(name)
    return ChainParser([create(name) for name in wanted], order)
