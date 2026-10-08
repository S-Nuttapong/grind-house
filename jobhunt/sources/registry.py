"""Which adapter serves a source id."""

from jobhunt.sources.ashby import AshbyAdapter
from jobhunt.sources.base import SourceAdapter
from jobhunt.sources.greenhouse import GreenhouseAdapter
from jobhunt.sources.lever import LeverAdapter

_ATS: dict[str, SourceAdapter] = {
    "greenhouse": GreenhouseAdapter(),
    "lever": LeverAdapter(),
    "ashby": AshbyAdapter(),
}


def adapter_for(source_id: str) -> SourceAdapter:
    adapter = _ATS.get(source_id)
    if adapter is None:
        raise ValueError(f"no adapter for source {source_id}")
    return adapter
