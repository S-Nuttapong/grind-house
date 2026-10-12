"""Run one scope, or every enabled scope for a source."""

from jobhunt.composition import COMPOSITION
from jobhunt.scrape.ingest import RunResult
from jobhunt.scrape.pipeline import ScrapePipeline


def scrape(*, scope_id: int | None, source_id: str | None) -> list[RunResult]:
    return ScrapePipeline(COMPOSITION).scrape(scope_id=scope_id, source_id=source_id)
