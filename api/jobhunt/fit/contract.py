"""Check a fit result. Unknown documents are dropped. Other mismatches are logged."""

from collections.abc import Sequence

from jobhunt.core.log import get_logger
from jobhunt.fit.base import DocMatch, FitResult
from jobhunt.fit.select import BUDGET

log = get_logger("fit")


def check_fit(result: FitResult, *, doc_ids: set[str], aspects: Sequence[str]) -> FitResult:
    """Drop matches that cite a document the scorer was not given."""
    known = set(aspects)
    kept: list[DocMatch] = []
    for match in result.top_docs:
        if match.brag_doc_id not in doc_ids:
            _log("fit_doc")
            continue
        if not 0 <= match.similarity <= 1:
            _log("fit_similarity")
            continue
        if match.aspect not in known:
            _log("fit_aspect")
        kept.append(match)
    if len(kept) > BUDGET:
        _log("fit_budget")
        kept = kept[:BUDGET]
    score = _clamp(result.score, 0, 100, "fit_score")
    coverage = _clamp(result.coverage, 0, 1, "fit_coverage")
    raw = result.raw if 0 <= result.raw <= 1 else _clamp(result.raw, 0, 1, "fit_raw")
    return FitResult(
        score=score,
        raw=raw,
        coverage=coverage,
        top_docs=kept,
        gaps=list(result.gaps),
    )


def _clamp(value: float, low: float, high: float, rule: str) -> float:
    if low <= value <= high:
        return value
    _log(rule)
    return max(low, min(high, value))


def _log(rule: str) -> None:
    log.info("contract_drop rule=%s", rule)
