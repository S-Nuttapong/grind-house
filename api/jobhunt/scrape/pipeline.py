"""Scrape using the sources, parser, and store on a Composition."""

from jobhunt.composition import Composition, require_on_machine
from jobhunt.core.http import HttpClient
from jobhunt.scrape.ingest import RunResult, run_scope
from jobhunt.scrape.sources.base import JobSource


class ScrapePipeline:
    def __init__(self, composition: Composition) -> None:
        self.composition = composition

    def source(self, source_id: str) -> JobSource:
        return self.composition.source(source_id)

    def scrape(self, *, scope_id: int | None, source_id: str | None) -> list[RunResult]:
        if scope_id is not None and source_id is not None:
            raise ValueError("pass either --scope or --source, not both")
        require_on_machine(self.composition.parser, "parser")
        targets = self.composition.store.scrape_targets(scope_id=scope_id, source_id=source_id)
        return [self.run(target_id, target_source) for target_id, target_source in targets]

    def run(self, scope_id: int, source_id: str, http: HttpClient | None = None) -> RunResult:
        require_on_machine(self.composition.parser, "parser")
        return run_scope(scope_id, self.source(source_id), http)
