from datetime import UTC, datetime

import numpy as np
from jobhunt.fit.bge import BgeFitModel
from jobhunt.fit.calibrate import calibrate, tier
from jobhunt.fit.chunking import CHUNK_CHARS, chunk_text
from jobhunt.fit.fake import FakeFitModel
from jobhunt.fit.keywords import compare
from jobhunt.fit.registry import create
from jobhunt.fit.schedule import describe, next_runs, validate


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

    def encode(self, texts: list[str], *, normalize_embeddings: bool) -> np.ndarray:
        for text in texts:
            self.axes.setdefault(text, len(self.axes))
        vectors = np.zeros((len(texts), len(self.axes)))
        for row, text in enumerate(texts):
            vectors[row, self.axes[text]] = 1.0
        return vectors


def test_bge_scores_from_best_chunk_matches() -> None:
    model = BgeFitModel(_AxisEncoder())
    profile = "built payments in go\n\nkafka pipelines"
    scores = model.score_many(profile, ["built payments in go", "something else entirely"])
    assert scores[0] == round(calibrate(1.0), 1)
    assert scores[1] == round(calibrate(0.0), 1)


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
    assert model.score("React and TypeScript", "react") == 50.0
    assert model.score_many("react", ["React and TypeScript", "no overlap here"]) == [50.0, 0.0]


def test_registry_resolves_fake_and_rejects_unknown(monkeypatch) -> None:
    monkeypatch.delenv("FIT_MODEL", raising=False)
    assert create("fake").model_id == "fake/v1"
    try:
        create("nope")
    except ValueError as exc:
        assert "nope" in str(exc)
    else:
        raise AssertionError("expected ValueError")


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
