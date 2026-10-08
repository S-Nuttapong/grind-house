"""Fit scores from BAAI/bge-base-en-v1.5 embeddings.

The model is loaded once, by the caller, and kept for the life of the process.
`encode` is synchronous and CPU-bound, so callers run `score_many` off the
event loop (a worker thread, or the fit worker process).
"""

from collections.abc import Sequence
from typing import Protocol

import numpy as np

from jobhunt.fit.base import JobFitModel
from jobhunt.fit.calibrate import calibrate
from jobhunt.fit.chunking import chunk_text

_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
_MODEL_NAME = "BAAI/bge-base-en-v1.5"


class _Encoder(Protocol):
    def encode(
        self, texts: list[str], *, normalize_embeddings: bool
    ) -> np.ndarray[tuple[int, int], np.dtype[np.float64]]: ...


class BgeFitModel(JobFitModel):
    model_id = "bge-base-en-v1.5/v1"

    def __init__(self, encoder: _Encoder) -> None:
        self._encoder = encoder

    def score(self, job_description: str, profile_text: str) -> float:
        return self.score_many(profile_text, [job_description])[0]

    def score_many(self, profile_text: str, job_descriptions: Sequence[str]) -> list[float]:
        """Mean, over each job's chunks, of that chunk's best match in the profile.

        One matrix product per call, no Python loop over pairs.
        """
        profile_chunks = chunk_text(profile_text) or [profile_text]
        per_job = [chunk_text(description) or [description] for description in job_descriptions]
        query_chunks = [_QUERY_PREFIX + chunk for chunks in per_job for chunk in chunks]

        # One call keeps every vector the same width, which a shared encoder needs.
        vectors = self._encoder.encode([*profile_chunks, *query_chunks], normalize_embeddings=True)
        profile_vectors = vectors[: len(profile_chunks)]
        query_vectors = vectors[len(profile_chunks) :]
        # Vectors are L2-normalised, so the dot product is the cosine similarity.
        similarities = query_vectors @ profile_vectors.T

        scores: list[float] = []
        cursor = 0
        for chunks in per_job:
            block = similarities[cursor : cursor + len(chunks)]
            raw = float(block.max(axis=1).mean())
            scores.append(round(calibrate(raw), 1))
            cursor += len(chunks)
        return scores


def load_encoder(cache_dir: str | None = None) -> _Encoder:
    """Load the model from disk. Downloads it on first use unless cached."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(_MODEL_NAME, cache_folder=cache_dir)
    return model  # type: ignore[no-any-return]
