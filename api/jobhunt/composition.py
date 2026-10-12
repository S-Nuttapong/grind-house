"""The only file that picks adapters. Swap a line here; do not add a lookup table."""

import os
from dataclasses import dataclass

from jobhunt.facts.base import DetailParser
from jobhunt.facts.default import DefaultParser
from jobhunt.fit.base import FitScorer
from jobhunt.fit.matrix import MatrixFitScorer
from jobhunt.resume.base import ResumeWriter
from jobhunt.resume.sdk import ClaudeSdkWriter
from jobhunt.scrape.sources.adzuna import AdzunaSource
from jobhunt.scrape.sources.ashby import AshbySource
from jobhunt.scrape.sources.base import JobSource
from jobhunt.scrape.sources.greenhouse import GreenhouseSource
from jobhunt.scrape.sources.jobspy_src import JobSpySource
from jobhunt.scrape.sources.jooble import JoobleSource
from jobhunt.scrape.sources.lever import LeverSource
from jobhunt.scrape.sources.linkedin import LinkedInSource
from jobhunt.scrape.sources.mycareersfuture import MyCareersFutureSource
from jobhunt.scrape.sources.reed import ReedSource
from jobhunt.scrape.sources.seek import SeekSource
from jobhunt.store import PgStore, Store


@dataclass(frozen=True)
class Composition:
    sources: list[JobSource]
    parser: DetailParser
    scorer: FitScorer
    writer: ResumeWriter
    store: Store

    def source(self, source_id: str) -> JobSource:
        for item in self.sources:
            if item.id == source_id:
                return item
        raise ValueError(f"no source for {source_id}")


def require_on_machine(adapter: object, label: str) -> None:
    """Refuse an adapter that sends text off this machine unless the operator opted in."""
    offsite = getattr(adapter, "sends_data_offsite", False)
    allowed = os.environ.get("JOBHUNT_ALLOW_OFFSITE") == "1"
    if offsite and not allowed:
        raise ValueError(
            f"{label} sends data off this machine; set JOBHUNT_ALLOW_OFFSITE=1 to load it"
        )


COMPOSITION = Composition(
    sources=[
        GreenhouseSource(),
        LeverSource(),
        AshbySource(),
        JobSpySource("indeed"),
        LinkedInSource(),
        SeekSource(),
        JobSpySource("glassdoor"),
        JobSpySource("ziprecruiter"),
        JobSpySource("naukri"),
        AdzunaSource(),
        ReedSource(),
        JoobleSource(),
        MyCareersFutureSource(),
    ],
    parser=DefaultParser(),
    scorer=MatrixFitScorer("qwen3"),
    writer=ClaudeSdkWriter(),
    store=PgStore(),
)
