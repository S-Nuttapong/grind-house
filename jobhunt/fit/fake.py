"""A deterministic model for tests. The score is the share of job terms the profile has."""

from collections.abc import Sequence

from jobhunt.fit.base import JobFitModel
from jobhunt.fit.keywords import terms_in


class FakeFitModel(JobFitModel):
    model_id = "fake/v1"

    def score(self, job_description: str, profile_text: str) -> float:
        job_terms = terms_in(job_description)
        if not job_terms:
            return 0.0
        overlap = len(job_terms & terms_in(profile_text))
        return round(100 * overlap / len(job_terms), 1)

    def score_many(self, profile_text: str, job_descriptions: Sequence[str]) -> list[float]:
        profile_terms = terms_in(profile_text)
        scores: list[float] = []
        for description in job_descriptions:
            job_terms = terms_in(description)
            if not job_terms:
                scores.append(0.0)
                continue
            scores.append(round(100 * len(job_terms & profile_terms) / len(job_terms), 1))
        return scores
