"""Claude fit scorer. Coverage and gaps are computed here, not by the model.

From v3 the model only returns matches. The score is computed in code from
those matches, so a high score always has evidence behind it.
"""

import math
import re
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, ConfigDict

from jobhunt.core.claude import ClaudeError, structured_call
from jobhunt.fit.aspects import split_aspects
from jobhunt.fit.base import BragDoc, FitResult, FitScorer, FitUnavailable
from jobhunt.fit.contract import check_fit
from jobhunt.fit.keywords import stack_terms_in
from jobhunt.fit.select import select_docs

_MODEL = "claude-haiku-5-5"
_PROMPT_VERSION = "v3"
# Haiku 5.5 thinking tokens count toward this cap.
_MAX_TOKENS = 16000

# The rubric's "adjacent" and "direct proof" anchors: no credit at or below
# TAU0, full credit at or above TAU1.
TAU0 = 0.5
TAU1 = 0.9
# Pseudo-requirements with no evidence, so a short job cannot score high on one match.
_PRIOR_ASPECTS = 2
# Below this many requirements the description is too thin to claim a fit.
MIN_ASPECTS = 3
_MIN_DOC_MATCHES = 3

_LINK_ONLY = re.compile(r"^\[[^\]]*\]\([^)]*\)\W*$")
_NOT_A_REQUIREMENT = re.compile(
    r"\b(equal (employment )?opportunity|eeo|affirmative action|benefits?|perks?"
    r"|paid time off|pto|401\(?k\)?|health insurance|parental leave|stock purchase"
    r"|salary|compensation)\b",
    re.IGNORECASE,
)

_RUBRIC = """Score how well the brag docs cover the job aspects in the user message.
score is 0 to 100.
Each match has aspect_index (0-based into the user list), brag_doc_id copied
from the list below, and similarity from 0 to 1.
Include a match only when that doc covers that aspect.
Do not invent a document id.
"""

# v2-rubric:start
_V2_RUBRIC = """Score how well the brag docs above cover the job aspects in the user message.
score is 0 to 100.
85 to 100 means the core stack and seniority match and most required bullets are covered.
60 to 84 means good overlap with a few gaps.
40 to 59 means adjacent experience.
Under 40 means a different stack or domain.
Each match has aspect_index (0-based into the user list), brag_doc_id copied
from a doc id above, and similarity from 0 to 1.
0.9 is direct proof with the same technology or domain.
0.7 is the same skill on a different stack.
0.5 is adjacent.
Below 0.5, leave the match out.
Match only real requirements.
Skip benefits, hiring steps, request ids, and slogans.
A named technology (Java, Rust, Kubernetes) needs a story that uses it.
Do not reuse one general story for unrelated bullets.
An unmatched bullet is fine.
Do not invent a document id.
"""
# v2-rubric:end

# v3-rubric:start
_V3_RUBRIC = """Match the brag docs above to the job aspects in the user message.
Each match has aspect_index (0-based into the user list), brag_doc_id copied
from a doc id above, and similarity from 0 to 1.
0.9 is direct proof with the same technology or domain.
0.7 is the same skill on a different stack.
0.5 is adjacent.
Below 0.5, leave the match out.
Match only real requirements.
Skip benefits, hiring steps, request ids, and slogans.
A named technology (Java, Rust, Kubernetes) needs a story that uses it.
Do not reuse one general story for unrelated bullets.
An unmatched bullet is fine.
Do not invent a document id.
"""
# v3-rubric:end

_EVIDENCE_VERSIONS = frozenset({"v3"})


class AspectMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aspect_index: int
    brag_doc_id: str
    similarity: float


class FitFields(BaseModel):
    """v1 and v2 replies. Every property is required. There is no reasoning field."""

    model_config = ConfigDict(extra="forbid")

    score: float
    matches: list[AspectMatch]


class MatchFields(BaseModel):
    """v3 replies: matches only. The score is computed from them."""

    model_config = ConfigDict(extra="forbid")

    matches: list[AspectMatch]


class ClaudeFitScorer(FitScorer):
    """One cached system block per doc set. Jobs are scored concurrency at a time."""

    sends_data_offsite = True

    def __init__(
        self,
        model: str = _MODEL,
        concurrency: int = 4,
        *,
        prompt_version: str | None = None,
        rubric: str | None = None,
    ) -> None:
        self.model = model
        self.concurrency = concurrency
        self.prompt_version = _PROMPT_VERSION if prompt_version is None else prompt_version
        self.rubric = rubric
        if self.prompt_version == "v1" and rubric is not None:
            raise ValueError("v1 does not take a rubric override")
        if self.prompt_version not in {"v1", "v2", "v3"} and rubric is None:
            raise ValueError(f"prompt version {self.prompt_version} needs a rubric")
        self.model_id = f"{model}/{self.prompt_version}"

    @property
    def scores_from_evidence(self) -> bool:
        return self.prompt_version in _EVIDENCE_VERSIONS

    def fit(
        self,
        docs: Sequence[BragDoc],
        job_description: str,
        *,
        max_retries: int = 3,
    ) -> FitResult:
        if self.scores_from_evidence:
            aspects = clean_aspects(job_description)
            if len(aspects) < MIN_ASPECTS:
                return _blank(aspects)
        else:
            aspects = split_aspects(job_description)
        if not docs or not aspects:
            return _blank(aspects)
        output: type[FitFields] | type[MatchFields] = (
            MatchFields if self.scores_from_evidence else FitFields
        )
        errors: list[str] = []
        parsed: FitFields | MatchFields | None = None
        for _attempt in range(max_retries + 1):
            try:
                parsed, _meta = structured_call(
                    model=self.model,
                    system=system_prompt(docs, version=self.prompt_version, rubric=self.rubric),
                    user=_user(aspects, errors),
                    output=output,
                    max_tokens=_MAX_TOKENS,
                )
            except ClaudeError as exc:
                raise FitUnavailable(str(exc)) from exc
            errors = fit_field_errors(parsed, docs, aspects)
            if not errors:
                break
        if parsed is None or errors:
            raise FitUnavailable("; ".join(errors))
        if self.scores_from_evidence:
            result = evidence_result(parsed, docs, aspects)
        else:
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


def clean_aspects(description: str) -> list[str]:
    """Requirement aspects without link-only, benefits, or equal-opportunity bullets."""
    return [
        aspect
        for aspect in split_aspects(description)
        if not _LINK_ONLY.match(aspect) and not _NOT_A_REQUIREMENT.search(aspect)
    ]


def evidence_score(
    best: Sequence[float],
    *,
    tau0: float = TAU0,
    tau1: float = TAU1,
    prior_aspects: int = _PRIOR_ASPECTS,
) -> float:
    """0 to 100 from the best similarity on each requirement.

    Credit ramps from 0 at tau0 to 1 at tau1. Coverage R is the credit over
    N plus the prior aspects. Quality P is the credit-weighted mean credit.
    The score is their harmonic mean, so both must be high.
    """
    credit = [_credit(value, tau0, tau1) for value in best]
    total = sum(credit)
    if total == 0:
        return 0.0
    coverage = total / (len(credit) + prior_aspects)
    quality = sum(value * value for value in credit) / total
    return round(100 * 2 * quality * coverage / (quality + coverage), 1)


def ground_matrix(
    matrix: list[list[float]], docs: Sequence[BragDoc], aspects: Sequence[str]
) -> list[list[float]]:
    """Zero matches the docs cannot back.

    A requirement that names a technology needs a doc that names one of the
    same technologies. Each doc keeps only its strongest matches, so one
    general story cannot cover every bullet.
    """
    aspect_terms = [stack_terms_in(aspect) for aspect in aspects]
    grounded: list[list[float]] = []
    for doc, row in zip(docs, matrix, strict=True):
        doc_terms = stack_terms_in(doc.text)
        grounded.append(
            [
                0.0 if terms and not terms & doc_terms else value
                for terms, value in zip(aspect_terms, row, strict=True)
            ]
        )
    keep = max(_MIN_DOC_MATCHES, math.ceil(len(aspects) / max(1, len(docs))))
    for row in grounded:
        ranked = sorted(range(len(row)), key=lambda column: (-row[column], column))
        for column in ranked[keep:]:
            row[column] = 0.0
    return grounded


def evidence_result(
    parsed: FitFields | MatchFields, docs: Sequence[BragDoc], aspects: list[str]
) -> FitResult:
    doc_ids = [doc.id for doc in docs]
    matrix = ground_matrix(_matrix(parsed, doc_ids, aspects), docs, aspects)
    selection = select_docs(matrix, doc_ids, aspects)
    index_of = {doc_id: index for index, doc_id in enumerate(doc_ids)}
    rows = [matrix[index_of[match.brag_doc_id]] for match in selection.top_docs]
    best = [max((row[column] for row in rows), default=0.0) for column in range(len(aspects))]
    gaps = [
        aspect
        for aspect, value in zip(aspects, best, strict=True)
        if _credit(value, TAU0, TAU1) == 0
    ]
    return FitResult(
        score=evidence_score(best),
        raw=selection.raw,
        coverage=selection.coverage,
        top_docs=selection.top_docs,
        gaps=gaps,
    )


def result_from_fields(
    parsed: FitFields | MatchFields, docs: Sequence[BragDoc], aspects: list[str]
) -> FitResult:
    """v1 and v2: the model's own score, with coverage and gaps from its matches."""
    doc_ids = [doc.id for doc in docs]
    selection = select_docs(_matrix(parsed, doc_ids, aspects), doc_ids, aspects)
    model_score = getattr(parsed, "score", 0.0)
    score = max(0.0, min(100.0, model_score))
    return FitResult(
        score=round(score, 1),
        raw=selection.raw,
        coverage=selection.coverage,
        top_docs=selection.top_docs,
        gaps=selection.gaps,
    )


def system_prompt(
    docs: Sequence[BragDoc], *, version: str = "v1", rubric: str | None = None
) -> str:
    """v1 is the original layout. Every other version puts rules after XML docs."""
    if version == "v1":
        return _system_v1(docs)
    if rubric is not None:
        text = rubric
    elif version == "v3":
        text = _V3_RUBRIC
    else:
        text = _V2_RUBRIC
    blocks = [f'<doc id="{doc.id}">\n{doc.text}\n</doc>' for doc in docs]
    blocks.append(text.strip())
    return "\n".join(blocks)


def _system_v1(docs: Sequence[BragDoc]) -> str:
    lines = [_RUBRIC, "Brag docs:"]
    for doc in docs:
        lines.append(f"id={doc.id}")
        lines.append(doc.text)
    return "\n".join(lines)


def fit_field_errors(
    parsed: FitFields | MatchFields,
    docs: Sequence[BragDoc],
    aspects: Sequence[str],
) -> list[str]:
    """Name each value that is outside the fit contract. An empty list is a good reply."""
    errors: list[str] = []
    score = getattr(parsed, "score", None)
    if score is not None and not 0 <= score <= 100:
        errors.append(f"score {score} is outside 0 to 100")
    known = {doc.id for doc in docs}
    last_aspect = len(aspects) - 1
    for index, match in enumerate(parsed.matches):
        if match.brag_doc_id not in known:
            errors.append(f"match {index} brag_doc_id {match.brag_doc_id!r} is unknown")
        if not 0 <= match.aspect_index <= last_aspect:
            errors.append(
                f"match {index} aspect_index {match.aspect_index} is outside 0 to {last_aspect}"
            )
        if not 0 <= match.similarity <= 1:
            errors.append(f"match {index} similarity {match.similarity} is outside 0 to 1")
    return errors


def _matrix(
    parsed: FitFields | MatchFields, doc_ids: list[str], aspects: list[str]
) -> list[list[float]]:
    index_of = {doc_id: index for index, doc_id in enumerate(doc_ids)}
    matrix = [[0.0 for _aspect in aspects] for _doc in doc_ids]
    for match in parsed.matches:
        row = index_of.get(match.brag_doc_id)
        if row is None or not 0 <= match.aspect_index < len(aspects):
            continue
        column = match.aspect_index
        matrix[row][column] = max(matrix[row][column], max(0.0, min(1.0, match.similarity)))
    return matrix


def _credit(similarity: float, tau0: float, tau1: float) -> float:
    return max(0.0, min(1.0, (similarity - tau0) / (tau1 - tau0)))


def _blank(aspects: list[str]) -> FitResult:
    return FitResult(score=0.0, raw=0.0, coverage=0.0, top_docs=[], gaps=list(aspects))


def _user(aspects: list[str], errors: Sequence[str] = ()) -> str:
    from jobhunt.core.prompt_fence import fence

    numbered = "\n".join(f"{index}. {aspect}" for index, aspect in enumerate(aspects))
    lines = [fence(numbered, "JOB POSTING")]
    if errors:
        lines.append("")
        lines.append("Fix these errors:")
        lines.extend(errors)
    return "\n".join(lines)
