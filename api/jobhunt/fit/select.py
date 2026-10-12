"""Pick brag docs that cover a job, then reduce the matrix to one score.

Greedy facility-location coverage (Lin and Bilmes, ACL 2011) adds, at each
step, the document that most increases the sum over aspects of the best
similarity so far. The score is the mean, over the selected rows, of each
row's maximum. That is the row-max-then-mean reduction, limited to the docs
that would go on a resume.
"""

from dataclasses import dataclass

from jobhunt.fit.base import DocMatch

BUDGET = 10
GAIN_EPSILON = 0.01
# An aspect whose best selected similarity is below this is a gap.
GAP_THRESHOLD = 0.35


@dataclass(frozen=True)
class Selection:
    raw: float
    coverage: float
    top_docs: list[DocMatch]
    gaps: list[str]


def select_docs(
    matrix: list[list[float]],
    doc_ids: list[str],
    aspects: list[str],
    *,
    budget: int = BUDGET,
    epsilon: float = GAIN_EPSILON,
    gap_threshold: float = GAP_THRESHOLD,
) -> Selection:
    """Select from a doc × aspect matrix. Similarities below 0 are treated as 0."""
    n_aspects = len(aspects)
    if len(doc_ids) != len(matrix):
        raise ValueError("doc_ids and matrix rows differ in length")
    if any(len(row) != n_aspects for row in matrix):
        raise ValueError("every matrix row must have one value per aspect")
    if not matrix or n_aspects == 0:
        return Selection(raw=0.0, coverage=0.0, top_docs=[], gaps=list(aspects))

    clamped = [[max(0.0, value) for value in row] for row in matrix]
    covered = [0.0] * n_aspects
    chosen: list[int] = []
    remaining = set(range(len(clamped)))
    while len(chosen) < budget and remaining:
        best_index: int | None = None
        best_gain = -1.0
        for index in remaining:
            gain = sum(
                value - covered[column]
                for column, value in enumerate(clamped[index])
                if value > covered[column]
            )
            if best_index is None or gain > best_gain or (gain == best_gain and index < best_index):
                best_gain = gain
                best_index = index
        if best_index is None or best_gain < epsilon:
            break
        chosen.append(best_index)
        remaining.remove(best_index)
        covered = [max(covered[column], clamped[best_index][column]) for column in range(n_aspects)]

    top_docs: list[DocMatch] = []
    for index in chosen:
        row = clamped[index]
        best_column = max(range(n_aspects), key=lambda column: (row[column], -column))
        top_docs.append(
            DocMatch(
                brag_doc_id=doc_ids[index],
                aspect=aspects[best_column],
                similarity=round(row[best_column], 6),
            )
        )
    if chosen:
        raw = sum(max(clamped[index]) for index in chosen) / len(chosen)
        coverage = sum(covered) / n_aspects
    else:
        raw = 0.0
        coverage = 0.0
    gaps = [aspects[column] for column, value in enumerate(covered) if value < gap_threshold]
    return Selection(raw=raw, coverage=coverage, top_docs=top_docs, gaps=gaps)
