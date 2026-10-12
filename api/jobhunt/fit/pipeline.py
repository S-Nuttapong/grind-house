"""Score jobs with the scorer on a Composition."""

from datetime import datetime

from jobhunt.composition import Composition, require_on_machine
from jobhunt.fit.worker import execute_run, poll_once, serve


class FitPipeline:
    def __init__(self, composition: Composition) -> None:
        self.composition = composition
        require_on_machine(composition.scorer, "fit scorer")

    def serve(self) -> None:
        serve(self.composition.scorer)

    def poll_once(self, *, now: datetime | None = None) -> None:
        poll_once(self.composition.scorer, now=now)

    def execute_run(self, run_id: int, *, limit: int | None = None) -> None:
        execute_run(self.composition.scorer, run_id, limit=limit)
