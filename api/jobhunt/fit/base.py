"""The contract every fit strategy implements. An embedding model, an LLM, or a custom model."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class BragDoc:
    """One profile document the model can select for a resume."""

    id: str
    text: str


@dataclass(frozen=True)
class DocMatch:
    """A selected document and the job aspect it covers best."""

    brag_doc_id: str
    aspect: str
    similarity: float


@dataclass(frozen=True)
class FitResult:
    """Fit of one job description against a set of brag docs."""

    score: float
    raw: float
    coverage: float
    top_docs: list[DocMatch]
    gaps: list[str]


class FitUnavailable(Exception):
    """This batch cannot be scored together. Callers score one job at a time."""


class FitRateLimited(FitUnavailable):
    """Claude returned 429 or a plan limit. Stop the run. Do not retry."""


class FitScorer(ABC):
    """Scores job descriptions against brag docs. Scores are 0 to 100."""

    model_id: str
    # True when scoring sends the docs or the job text to another machine.
    sends_data_offsite: bool = False

    @abstractmethod
    def fit(self, docs: Sequence[BragDoc], job_description: str) -> FitResult:
        """Return the fit of one job description, including the docs to build a resume from."""

    def fit_many(self, docs: Sequence[BragDoc], job_descriptions: Sequence[str]) -> list[FitResult]:
        """Score many job descriptions. Strategies override this to batch the work."""
        return [self.fit(docs, description) for description in job_descriptions]
