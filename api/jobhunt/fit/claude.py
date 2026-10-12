"""Claude fit scorer. Coverage and gaps are computed here, not by the model."""

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, ConfigDict

from jobhunt.core.claude import ClaudeError, structured_call
from jobhunt.fit.aspects import split_aspects
from jobhunt.fit.base import BragDoc, FitResult, FitUnavailable
from jobhunt.fit.contract import check_fit
from jobhunt.fit.select import select_docs

_MODEL = "claude-haiku-5-5"
_PROMPT_VERSION = "v1"
_MAX_TOKENS = 2048

_RUBRIC = """Score how well the brag docs cover the job aspects in the user message.
score is 0 to 100.
Each match has aspect_index (0-based into the user list), brag_doc_id copied
from the list below, and similarity from 0 to 1.
Include a match only when that doc covers that aspect.
Do not invent a document id.
"""


class AspectMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aspect_index: int
    brag_doc_id: str
    similarity: float


class FitFields(BaseModel):
    """Every property is required. There is no reasoning field."""

    model_config = ConfigDict(extra="forbid")

    score: float
    matches: list[AspectMatch]


class ClaudeFitScorer:
    """One cached system block per doc set. Jobs are scored concurrency at a time."""

    sends_data_offsite = True

    def __init__(self, model: str = _MODEL, concurrency: int = 4) -> None:
        self.model = model
        self.concurrency = concurrency
        self.model_id = f"{model}/{_PROMPT_VERSION}"

    def fit(self, docs: Sequence[BragDoc], job_description: str) -> FitResult:
        aspects = split_aspects(job_description)
        if not docs or not aspects:
            return FitResult(score=0.0, raw=0.0, coverage=0.0, top_docs=[], gaps=list(aspects))
        try:
            parsed, _meta = structured_call(
                model=self.model,
                system=_system(docs),
                user=_user(aspects),
                output=FitFields,
                max_tokens=_MAX_TOKENS,
            )
        except ClaudeError as exc:
            raise FitUnavailable(str(exc)) from exc
        result = result_from_fields(parsed, docs, aspects)
        return check_fit(result, doc_ids={doc.id for doc in docs}, aspects=aspects)

    def fit_many(self, docs: Sequence[BragDoc], job_descriptions: Sequence[str]) -> list[FitResult]:
        if len(job_descriptions) <= 1:
            return [self.fit(docs, description) for description in job_descriptions]
        workers = max(1, min(self.concurrency, len(job_descriptions)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(self.fit, docs, description) for description in job_descriptions]
            results: list[FitResult] = []
            for future in futures:
                try:
                    results.append(future.result())
                except FitUnavailable:
                    raise
                except Exception as exc:
                    raise FitUnavailable(str(exc)) from exc
            return results


def result_from_fields(parsed: FitFields, docs: Sequence[BragDoc], aspects: list[str]) -> FitResult:
    doc_ids = [doc.id for doc in docs]
    index_of = {doc_id: index for index, doc_id in enumerate(doc_ids)}
    matrix = [[0.0 for _aspect in aspects] for _doc in docs]
    for match in parsed.matches:
        row = index_of.get(match.brag_doc_id)
        if row is None or not 0 <= match.aspect_index < len(aspects):
            continue
        column = match.aspect_index
        matrix[row][column] = max(matrix[row][column], max(0.0, min(1.0, match.similarity)))
    selection = select_docs(matrix, doc_ids, aspects)
    score = max(0.0, min(100.0, parsed.score))
    return FitResult(
        score=round(score, 1),
        raw=selection.raw,
        coverage=selection.coverage,
        top_docs=selection.top_docs,
        gaps=selection.gaps,
    )


def _system(docs: Sequence[BragDoc]) -> str:
    lines = [_RUBRIC, "Brag docs:"]
    for doc in docs:
        lines.append(f"id={doc.id}")
        lines.append(doc.text)
    return "\n".join(lines)


def _user(aspects: list[str]) -> str:
    lines = ["Aspects:"]
    for index, aspect in enumerate(aspects):
        lines.append(f"{index}. {aspect}")
    return "\n".join(lines)
