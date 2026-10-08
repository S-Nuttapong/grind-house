"""Which adapter serves a source id."""

from jobhunt.sources.ashby import AshbyAdapter
from jobhunt.sources.base import SourceAdapter
from jobhunt.sources.greenhouse import GreenhouseAdapter
from jobhunt.sources.jobspy_src import JobSpyAdapter
from jobhunt.sources.lever import LeverAdapter

_ADAPTERS: dict[str, SourceAdapter] = {
    "greenhouse": GreenhouseAdapter(),
    "lever": LeverAdapter(),
    "ashby": AshbyAdapter(),
    "indeed": JobSpyAdapter("indeed"),
    "linkedin_guest": JobSpyAdapter("linkedin_guest"),
    "glassdoor": JobSpyAdapter("glassdoor"),
    "ziprecruiter": JobSpyAdapter("ziprecruiter"),
}


def adapter_for(source_id: str) -> SourceAdapter:
    adapter = _ADAPTERS.get(source_id)
    if adapter is None:
        raise ValueError(f"no adapter for source {source_id}")
    return adapter
