from datetime import UTC, datetime

import numpy as np
import pytest
from jobhunt.fit.base import BragDoc, JobFitModel
from jobhunt.fit.calibrate import calibrate, suggest_floor_span, tier
from jobhunt.fit.chunking import CHUNK_CHARS, chunk_text
from jobhunt.fit.eval import hit_at_k, spearman
from jobhunt.fit.fake import FakeFitModel
from jobhunt.fit.keywords import compare
from jobhunt.fit.matrix import QWEN3, EncoderConfig, MatrixFitModel
from jobhunt.fit.registry import create, register
from jobhunt.fit.schedule import describe, next_runs, validate
from jobhunt.fit.sources import docs_hash, resume_sections


def test_calibration_clamps_to_the_range() -> None:
    assert calibrate(0.40) == 0
    assert calibrate(0.85) == 100
    assert calibrate(0.10) == 0
    assert calibrate(0.99) == 100
    assert round(calibrate(0.625), 6) == 50


def test_tiers() -> None:
    assert [tier(score) for score in (80, 60, 40, 39.9)] == ["strong", "good", "fair", "low"]


class _AxisEncoder:
    """Embeddings where each text's vector is one axis, so matches are exact."""

    def __init__(self) -> None:
        self.axes: dict[str, int] = {}
        self.prompts: list[str | None] = []

    def encode(self, texts: list[str], *, normalize_embeddings: bool, prompt: str | None = None):
        _ = normalize_embeddings
        self.prompts.append(prompt)
        bare = [text.removeprefix(QWEN3.query_prefix) for text in texts]
        for text in bare:
            self.axes.setdefault(text, len(self.axes))
        vectors = np.zeros((len(texts), 32))
        for row, text in enumerate(bare):
            vectors[row, self.axes[text]] = 1.0
        return vectors


def test_matrix_model_matches_each_aspect_and_batches_one_encode() -> None:
    encoder = _AxisEncoder()
    model = MatrixFitModel(encoder, QWEN3)
    docs = [
        BragDoc(id="b1", text="alpha requirement story"),
        BragDoc(id="b2", text="beta requirement story"),
    ]
    results = model.fit_many(
        docs,
        [
            "- alpha requirement story\n- beta requirement story",
            "unrelated requirement text.",
        ],
    )
    assert results[0].score == round(calibrate(1.0), 1)
    assert [match.brag_doc_id for match in results[0].top_docs] == ["b1", "b2"]
    assert results[1].score == round(calibrate(0.0), 1)
    assert encoder.prompts == [None, QWEN3.query_prompt]


def test_matrix_model_scores_nothing_without_docs() -> None:
    encoder = _AxisEncoder()
    result = MatrixFitModel(
        encoder,
        EncoderConfig(
            model_id="test/v1",
            hf_name="unused",
            query_prefix="",
            query_prompt=None,
            floor=0.40,
            span=0.45,
        ),
    ).fit([], "alpha requirement story.")
    assert result.score == 0.0
    assert result.gaps == ["alpha requirement story."]
    assert encoder.prompts == []


def test_chunking_keeps_paragraphs_and_splits_long_ones() -> None:
    text = "a" * 20 + "\n\n" + "b" * 20
    assert chunk_text(text, size=100) == ["a" * 20 + "\n\n" + "b" * 20]
    assert chunk_text(text, size=25) == ["a" * 20, "b" * 20]
    long = "x" * (CHUNK_CHARS + 50)
    pieces = chunk_text(long)
    assert len(pieces) == 2
    assert "".join(pieces) == long


def test_keywords_match_synonyms_and_report_gaps() -> None:
    matched, missing = compare(
        "Shipped a React.js app for a payments team",
        "Looking for React and TypeScript experience in fintech",
    )
    assert matched == ["fintech", "react"]
    assert missing == ["typescript"]


def test_fake_model_is_deterministic() -> None:
    model = FakeFitModel()
    docs = [BragDoc(id="a", text="react")]
    assert model.fit(docs, "React and TypeScript").score == 50.0
    scores = [
        result.score for result in model.fit_many(docs, ["React and TypeScript", "no overlap here"])
    ]
    assert scores == [50.0, 0.0]


def test_registry_resolves_fake_and_rejects_unknown(monkeypatch) -> None:
    monkeypatch.delenv("FIT_MODEL", raising=False)
    assert create("fake").model_id == "fake/v1"
    try:
        create("nope")
    except ValueError as exc:
        assert "nope" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_offsite_model_requires_an_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    from jobhunt.fit.base import FitResult

    class Offsite(JobFitModel):
        model_id = "off/v1"
        sends_data_offsite = True

        def fit(self, docs, job_description: str) -> FitResult:
            return FitResult(score=0.0, raw=0.0, coverage=0.0, top_docs=[], gaps=[])

    register("off", Offsite)
    try:
        monkeypatch.delenv("FIT_ALLOW_OFFSITE", raising=False)
        with pytest.raises(ValueError, match="FIT_ALLOW_OFFSITE"):
            create("off")
        monkeypatch.setenv("FIT_ALLOW_OFFSITE", "1")
        assert create("off").model_id == "off/v1"
    finally:
        from jobhunt.fit import registry

        del registry._FACTORIES["off"]


def test_schedule_validation() -> None:
    assert validate("0 6 * * *", "Asia/Bangkok") == []
    assert "not a valid cron" in validate("not a cron", "Asia/Bangkok")[0]
    assert "not a known timezone" in validate("0 6 * * *", "Mars/Base")[0]
    assert "minimum is 15" in validate("*/5 * * * *", "Asia/Bangkok")[0]


def test_schedule_preview() -> None:
    assert "06:00" in describe("0 6 * * *")
    start = datetime(2026, 10, 8, 0, tzinfo=UTC)
    runs = next_runs("0 6 * * *", "Asia/Bangkok", 3, now=start)
    assert [run.hour for run in runs] == [6, 6, 6]
    assert all(run.tzname() == "+07" for run in runs)


def test_aspects_drop_boilerplate_and_keep_requirement_bullets() -> None:
    from jobhunt.fit.aspects import split_aspects

    description = """
## Requirements
- Build React design systems used by 90 repositories

## Benefits
- Health insurance and a free lunch every day
"""
    assert split_aspects(description) == ["Build React design systems used by 90 repositories"]


def test_aspects_fall_back_to_chunks_when_nothing_is_usable() -> None:
    from jobhunt.fit.aspects import split_aspects

    assert split_aspects("hi") == ["hi"]


def test_greedy_selection_covers_distinct_aspects_then_stops() -> None:
    from jobhunt.fit.select import select_docs

    matrix = [
        [1.0, 0.0],
        [0.0, 1.0],
        [0.2, 0.0],
    ]
    selection = select_docs(matrix, ["b1", "b2", "b3"], ["aspect a", "aspect b"])
    assert [match.brag_doc_id for match in selection.top_docs] == ["b1", "b2"]
    assert selection.raw == 1.0
    assert selection.coverage == 1.0
    assert selection.gaps == []

    limited = select_docs(matrix, ["b1", "b2", "b3"], ["aspect a", "aspect b"], budget=1)
    assert [match.brag_doc_id for match in limited.top_docs] == ["b1"]

    tiny = select_docs([[0.005, 0.0], [0.0, 0.005]], ["b1", "b2"], ["a", "b"], epsilon=0.01)
    assert tiny.top_docs == []
    assert tiny.raw == 0.0
    assert tiny.gaps == ["a", "b"]


def test_score_is_the_mean_of_selected_row_maxima() -> None:
    from jobhunt.fit.select import select_docs

    selection = select_docs([[1.0, 0.0], [0.0, 0.5]], ["b1", "b2"], ["a", "b"], epsilon=0.0)
    assert selection.raw == 0.75
    assert selection.coverage == 0.75
    assert selection.gaps == []


def test_calibration_suggestion_uses_the_outer_percentiles() -> None:
    suggestion = suggest_floor_span([0.2, 0.4, 0.6, 0.8])
    assert suggestion is not None
    floor, span = suggestion
    assert floor < 0.4
    assert floor + span > 0.6
    assert suggest_floor_span([0.5]) is None
    assert suggest_floor_span([0.5, 0.5]) is None


def test_eval_metrics() -> None:
    assert spearman([1, 2, 3], [1, 2, 3]) == pytest.approx(1)
    assert spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1)
    assert spearman([1], [1]) is None
    assert spearman([1, 1, 1], [1, 2, 3]) is None
    assert hit_at_k([["a", "b"], ["c"]], [["b"], ["z"]], 2) == 0.5
    assert hit_at_k([["a"]], [[]], 10) is None


def test_resume_sections_and_doc_hash() -> None:
    docs = resume_sections(3, "# One\nalpha\n\n# Two\nbeta")
    assert [doc.id for doc in docs] == ["resume:3#1", "resume:3#2"]
    assert docs_hash(docs) != docs_hash([BragDoc(id="other", text=docs[0].text)])
