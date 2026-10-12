"""A deterministic model for tests. The score is term overlap, per brag doc."""

from collections.abc import Sequence

from jobhunt.fit.aspects import split_aspects
from jobhunt.fit.base import BragDoc, FitResult, JobFitModel
from jobhunt.fit.keywords import terms_in
from jobhunt.fit.select import select_docs


class FakeFitModel(JobFitModel):
    model_id = "fake/v1"

    def fit(self, docs: Sequence[BragDoc], job_description: str) -> FitResult:
        aspects = split_aspects(job_description)
        if not docs or not aspects:
            return FitResult(score=0.0, raw=0.0, coverage=0.0, top_docs=[], gaps=aspects)
        matrix: list[list[float]] = []
        for doc in docs:
            doc_terms = terms_in(doc.text)
            row: list[float] = []
            for aspect in aspects:
                aspect_terms = terms_in(aspect)
                if not aspect_terms:
                    row.append(0.0)
                else:
                    row.append(len(doc_terms & aspect_terms) / len(aspect_terms))
            matrix.append(row)
        selection = select_docs(matrix, [doc.id for doc in docs], aspects)
        # Overlap is already 0 to 1, so the score is that ratio on the 0–100 scale.
        return FitResult(
            score=round(selection.raw * 100, 1),
            raw=selection.raw,
            coverage=selection.coverage,
            top_docs=selection.top_docs,
            gaps=selection.gaps,
        )
