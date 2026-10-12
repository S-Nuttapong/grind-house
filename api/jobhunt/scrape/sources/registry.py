"""Which adapter serves a source id."""

from jobhunt.scrape.sources.adzuna import AdzunaAdapter
from jobhunt.scrape.sources.ashby import AshbyAdapter
from jobhunt.scrape.sources.base import SourceAdapter
from jobhunt.scrape.sources.greenhouse import GreenhouseAdapter
from jobhunt.scrape.sources.jobspy_src import JobSpyAdapter
from jobhunt.scrape.sources.jooble import JoobleAdapter
from jobhunt.scrape.sources.lever import LeverAdapter
from jobhunt.scrape.sources.linkedin import LinkedInAdapter
from jobhunt.scrape.sources.mycareersfuture import MyCareersFutureAdapter
from jobhunt.scrape.sources.reed import ReedAdapter
from jobhunt.scrape.sources.seek import SeekAdapter

_ADAPTERS: dict[str, SourceAdapter] = {
    "greenhouse": GreenhouseAdapter(),
    "lever": LeverAdapter(),
    "ashby": AshbyAdapter(),
    "indeed": JobSpyAdapter("indeed"),
    "linkedin_guest": LinkedInAdapter(),
    "seek": SeekAdapter(),
    "glassdoor": JobSpyAdapter("glassdoor"),
    "ziprecruiter": JobSpyAdapter("ziprecruiter"),
    "naukri": JobSpyAdapter("naukri"),
    "adzuna": AdzunaAdapter(),
    "reed": ReedAdapter(),
    "jooble": JoobleAdapter(),
    "mycareersfuture": MyCareersFutureAdapter(),
}


def adapter_for(source_id: str) -> SourceAdapter:
    adapter = _ADAPTERS.get(source_id)
    if adapter is None:
        raise ValueError(f"no adapter for source {source_id}")
    return adapter
