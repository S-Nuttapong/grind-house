"""Order brag docs that can fill space under the shortlist."""

from collections.abc import Sequence

from jobhunt.fit.base import BragDoc, JobFitModel
from jobhunt.fit.matrix import MatrixFitModel


def rank_filler(
    model: JobFitModel,
    docs: Sequence[BragDoc],
    shortlist_ids: set[str],
    impacts: dict[str, int | None],
    job_description: str,
) -> list[BragDoc]:
    """Impact descending, unrated last, then similarity to this job."""
    pool = [doc for doc in docs if doc.id not in shortlist_ids and doc.id != "profile"]
    scores = _relevance(model, pool, job_description)

    def sort_key(doc: BragDoc) -> tuple[bool, int, float, str]:
        impact = impacts.get(doc.id)
        return (impact is None, -(impact or 0), -scores.get(doc.id, 0.0), doc.id)

    return sorted(pool, key=sort_key)


def _relevance(model: JobFitModel, docs: list[BragDoc], job_description: str) -> dict[str, float]:
    if not docs:
        return {}
    if isinstance(model, MatrixFitModel):
        return model.max_per_doc(docs, job_description)
    return {doc.id: model.fit([doc], job_description).raw for doc in docs}
