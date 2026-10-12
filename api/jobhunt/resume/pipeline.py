"""Generate resumes with the writer and scorer on a Composition."""

from jobhunt.composition import Composition, require_on_machine
from jobhunt.resume.worker import execute_run, serve


class ResumePipeline:
    def __init__(self, composition: Composition) -> None:
        self.composition = composition
        require_on_machine(composition.writer, "resume writer")
        require_on_machine(composition.scorer, "fit scorer")

    def serve(self, *, handle_signals: bool = True) -> None:
        serve(self.composition.writer, self.composition.scorer, handle_signals=handle_signals)

    def execute_run(self, run_id: int) -> None:
        execute_run(self.composition.writer, self.composition.scorer, run_id)
