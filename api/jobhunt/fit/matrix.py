"""Doc × aspect fit from a local embedding model.

The encoder is injected so tests never download a model, and so Qwen3 and BGE
share one reduction. Qwen3-Embedding-0.6B is the starter: an embedding model,
not a generator (Zhang et al., arXiv:2506.05176).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, cast

import numpy as np

from jobhunt.fit.aspects import split_aspects
from jobhunt.fit.base import BragDoc, FitResult, FitScorer
from jobhunt.fit.calibrate import calibrate
from jobhunt.fit.select import BUDGET, select_docs

# Qwen3 was trained to read an instruction before the query. The authors report
# that a task-specific instruction changes retrieval by about 1–5%.
_QUERY_INSTRUCTION = (
    "Instruct: Given a job requirement, retrieve resume achievements that demonstrate it\nQuery:"
)
_BGE_PREFIX = "Represent this sentence for searching relevant passages: "


class Encoder(Protocol):
    def encode(
        self,
        texts: list[str],
        *,
        normalize_embeddings: bool,
        prompt: str | None = None,
    ) -> np.ndarray[tuple[int, int], np.dtype[np.float64]]: ...


@dataclass(frozen=True)
class EncoderConfig:
    model_id: str
    hf_name: str
    query_prefix: str
    query_prompt: str | None
    floor: float
    span: float
    budget: int = BUDGET
    left_pad: bool = False


# Provisional until `jobhunt fit calibrate` is run on real scores. Qwen3's
# cosine range is not published for job text, so it starts on the BGE span.
QWEN3 = EncoderConfig(
    model_id="qwen3-embedding-0.6b/v1",
    hf_name="Qwen/Qwen3-Embedding-0.6B",
    query_prefix="",
    query_prompt=_QUERY_INSTRUCTION,
    floor=0.40,
    span=0.45,
    left_pad=True,
)
BGE = EncoderConfig(
    model_id="bge-base-en-v1.5/v2-matrix",
    hf_name="BAAI/bge-base-en-v1.5",
    query_prefix=_BGE_PREFIX,
    query_prompt=None,
    floor=0.40,
    span=0.45,
)
CONFIGS: dict[str, EncoderConfig] = {"qwen3": QWEN3, "bge": BGE}


class MatrixFitScorer(FitScorer):
    """One cosine matrix per job description, then greedy coverage over the docs."""

    def __init__(self, encoder: Encoder | str, config: EncoderConfig | None = None) -> None:
        if isinstance(encoder, str):
            chosen = CONFIGS.get(encoder)
            if chosen is None:
                known = ", ".join(sorted(CONFIGS))
                raise ValueError(f"unknown matrix model {encoder!r}; known: {known}")
            self.name = encoder
            self._config = chosen
            self.model_id = chosen.model_id
            self._encoder: Encoder | None = None
            return
        if config is None:
            raise ValueError("config is required when an encoder is passed")
        self.name = config.model_id
        self._config = config
        self.model_id = config.model_id
        self._encoder = encoder

    def fit(self, docs: Sequence[BragDoc], job_description: str) -> FitResult:
        return self.fit_many(docs, [job_description])[0]

    def fit_many(self, docs: Sequence[BragDoc], job_descriptions: Sequence[str]) -> list[FitResult]:
        aspects_per_job = [split_aspects(description) for description in job_descriptions]
        if not docs or not any(aspects_per_job):
            return [_blank(aspects) for aspects in aspects_per_job]

        doc_vectors = self._encode([doc.text for doc in docs], prompt=None, prefix="")
        flat_aspects = [aspect for aspects in aspects_per_job for aspect in aspects]
        aspect_vectors = self._encode(
            flat_aspects, prompt=self._config.query_prompt, prefix=self._config.query_prefix
        )
        # L2-normalised vectors, so the product is the cosine similarity.
        similarities = aspect_vectors @ doc_vectors.T

        results: list[FitResult] = []
        cursor = 0
        doc_ids = [doc.id for doc in docs]
        for aspects in aspects_per_job:
            if not aspects:
                results.append(_blank(aspects))
                continue
            block = similarities[cursor : cursor + len(aspects)]
            cursor += len(aspects)
            selection = select_docs(block.T.tolist(), doc_ids, aspects, budget=self._config.budget)
            results.append(
                FitResult(
                    score=_calibrated(selection.raw, self._config),
                    raw=selection.raw,
                    coverage=selection.coverage,
                    top_docs=selection.top_docs,
                    gaps=selection.gaps,
                )
            )
        return results

    def max_per_doc(self, docs: Sequence[BragDoc], job_description: str) -> dict[str, float]:
        """Best cosine of each doc against any aspect. Used to rank filler, not to score."""
        aspects = split_aspects(job_description)
        if not docs or not aspects:
            return {doc.id: 0.0 for doc in docs}
        doc_vectors = self._encode([doc.text for doc in docs], prompt=None, prefix="")
        aspect_vectors = self._encode(
            aspects, prompt=self._config.query_prompt, prefix=self._config.query_prefix
        )
        similarities = aspect_vectors @ doc_vectors.T
        best = similarities.max(axis=0)
        return {doc.id: float(best[index]) for index, doc in enumerate(docs)}

    def _encode(
        self, texts: list[str], *, prompt: str | None, prefix: str
    ) -> np.ndarray[tuple[int, int], np.dtype[np.float64]]:
        prepared = [prefix + text for text in texts] if prefix else list(texts)
        encoded = self._loaded().encode(prepared, normalize_embeddings=True, prompt=prompt)
        array = np.asarray(encoded, dtype=np.float64)
        if array.ndim == 1:
            return array.reshape(1, -1)
        return array

    def _loaded(self) -> Encoder:
        if self._encoder is None:
            import os

            self._encoder = load_encoder(self._config, os.environ.get("HF_HOME"))
        return self._encoder


def _blank(aspects: list[str]) -> FitResult:
    return FitResult(score=0.0, raw=0.0, coverage=0.0, top_docs=[], gaps=list(aspects))


def _calibrated(raw: float, config: EncoderConfig) -> float:
    scaled = calibrate(raw, floor=config.floor, span=config.span)
    return round(max(0.0, min(100.0, scaled)), 1)


def load_matrix(name: str, cache_dir: str | None = None) -> MatrixFitScorer:
    """Load a named encoder now. Downloads the weights unless they are cached."""
    scorer = MatrixFitScorer(name)
    scorer._encoder = load_encoder(scorer._config, cache_dir)
    return scorer


def load_encoder(config: EncoderConfig, cache_dir: str | None = None) -> Encoder:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(config.hf_name, cache_folder=cache_dir, device="cpu")
    tokenizer = getattr(model, "tokenizer", None)
    if config.left_pad and tokenizer is not None and hasattr(tokenizer, "padding_side"):
        tokenizer.padding_side = "left"
    return _TransformerEncoder(cast(_RawEncoder, model))


class _RawEncoder(Protocol):
    def encode(self, texts: list[str], **kwargs: object) -> object: ...


class _TransformerEncoder:
    def __init__(self, model: _RawEncoder) -> None:
        self._model = model

    def encode(
        self,
        texts: list[str],
        *,
        normalize_embeddings: bool,
        prompt: str | None = None,
    ) -> np.ndarray[tuple[int, int], np.dtype[np.float64]]:
        kwargs: dict[str, object] = {
            "normalize_embeddings": normalize_embeddings,
            # fp32 forwards of the default batch exhaust a laptop; each text is
            # normalized on its own, so a smaller batch does not change the vectors.
            "batch_size": 4,
        }
        if prompt:
            kwargs["prompt"] = prompt
        encoded = self._model.encode(texts, **kwargs)
        return cast(
            "np.ndarray[tuple[int, int], np.dtype[np.float64]]",
            np.asarray(encoded),
        )
