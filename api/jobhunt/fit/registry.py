"""Maps a model name to its factory. Adding a strategy is one line in `_FACTORIES`."""

import os
from collections.abc import Callable

from jobhunt.fit.base import JobFitModel
from jobhunt.fit.fake import FakeFitModel

_FACTORIES: dict[str, Callable[[], JobFitModel]] = {
    "fake": FakeFitModel,
    "qwen3": lambda: _matrix("qwen3"),
    "bge": lambda: _matrix("bge"),
}


def register(name: str, factory: Callable[[], JobFitModel]) -> None:
    _FACTORIES[name] = factory


def names() -> list[str]:
    return sorted(_FACTORIES)


def create(name: str | None = None) -> JobFitModel:
    chosen = name or os.environ.get("FIT_MODEL", "qwen3")
    factory = _FACTORIES.get(chosen)
    if factory is None:
        known = ", ".join(names())
        raise ValueError(f"unknown fit model {chosen!r}; known: {known}")
    model = factory()
    if model.sends_data_offsite and os.environ.get("FIT_ALLOW_OFFSITE") != "1":
        raise ValueError(
            f"{chosen} sends brag docs off this machine; set FIT_ALLOW_OFFSITE=1 to load it"
        )
    return model


def _matrix(name: str) -> JobFitModel:
    from jobhunt.fit.matrix import load_matrix

    return load_matrix(name, os.environ.get("HF_HOME"))
