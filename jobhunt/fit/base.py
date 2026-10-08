"""The contract every fit strategy implements. Claude, Cursor, or any LLM later."""

from abc import ABC, abstractmethod
from collections.abc import Sequence


class JobFitModel(ABC):
    """Scores one profile text against job descriptions. Scores are 0 to 100."""

    model_id: str
    # True when scoring sends the profile or the job text to another machine.
    sends_data_offsite: bool = False

    @abstractmethod
    def score(self, job_description: str, profile_text: str) -> float:
        """Return the fit of one job description against the profile, from 0 to 100."""

    def score_many(self, profile_text: str, job_descriptions: Sequence[str]) -> list[float]:
        """Score many job descriptions. Strategies override this to batch the work."""
        return [self.score(description, profile_text) for description in job_descriptions]
