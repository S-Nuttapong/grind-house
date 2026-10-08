"""Maps a model name to its factory. Adding a strategy is one line in `_FACTORIES`."""

import os
from collections.abc import Callable

from jobhunt.fit.base import JobFitModel
from jobhunt.fit.fake import FakeFitModel

_FACTORIES: dict[str, Callable[[], JobFitModel]] = {
    "fake": FakeFitModel,
}


def register(name: str, factory: Callable[[], JobFitModel]) -> None:
    _FACTORIES[name] = factory


def create(name: str | None = None) -> JobFitModel:
    chosen = name or os.environ.get("FIT_MODEL", "bge")
    if chosen == "bge" and "bge" not in _FACTORIES:
        _FACTORIES["bge"] = _bge_factory()
    factory = _FACTORIES.get(chosen)
    if factory is None:
        known = ", ".join(sorted(_FACTORIES))
        raise ValueError(f"unknown fit model {chosen!r}; known: {known}")
    return factory()


def _bge_factory() -> Callable[[], JobFitModel]:
    def build() -> JobFitModel:
        from jobhunt.fit.bge import BgeFitModel, load_encoder

        cache_dir = os.environ.get("HF_HOME")
        return BgeFitModel(load_encoder(cache_dir))

    return build
