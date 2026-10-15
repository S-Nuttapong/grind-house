"""Claude fit mapping and contract. No network."""

import pytest
from jobhunt.core.claude import ClaudeTruncated
from jobhunt.fit.base import BragDoc, DocMatch, FitResult, FitUnavailable
from jobhunt.fit.claude import (
    AspectMatch,
    ClaudeFitScorer,
    FitFields,
    fit_field_errors,
    result_from_fields,
)
from jobhunt.fit.contract import check_fit


def test_coverage_and_gaps_are_computed_from_matches() -> None:
    docs = [BragDoc(id="doc-1", text="Built APIs")]
    aspects = ["Build APIs for the billing service today"]
    parsed = FitFields(
        score=82,
        matches=[AspectMatch(aspect_index=0, brag_doc_id="doc-1", similarity=0.9)],
    )
    result = result_from_fields(parsed, docs, aspects)
    assert result.score == 82
    assert result.top_docs[0].brag_doc_id == "doc-1"
    assert result.coverage > 0
    assert result.gaps == []


def test_an_unknown_document_is_dropped() -> None:
    result = FitResult(
        score=140,
        raw=2,
        coverage=0.5,
        top_docs=[
            DocMatch(brag_doc_id="missing", aspect="Build APIs", similarity=0.8),
            DocMatch(brag_doc_id="doc-1", aspect="Build APIs", similarity=0.4),
        ],
        gaps=[],
    )
    checked = check_fit(result, doc_ids={"doc-1"}, aspects=["Build APIs"])
    assert [match.brag_doc_id for match in checked.top_docs] == ["doc-1"]
    assert checked.score == 100
    assert checked.raw == 1


def test_field_errors_name_a_bad_score_id_index_and_similarity() -> None:
    parsed = FitFields(
        score=140,
        matches=[AspectMatch(aspect_index=3, brag_doc_id="missing", similarity=1.4)],
    )
    errors = fit_field_errors(parsed, [BragDoc(id="doc-1", text="Built APIs")], ["Build APIs"])
    text = " ".join(errors)
    assert "score 140" in text
    assert "missing" in text
    assert "aspect_index 3" in text
    assert "similarity 1.4" in text


def test_fit_retries_a_bad_reply_then_keeps_the_valid_one(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def invoke(**kwargs: object) -> tuple[FitFields, None]:
        user = str(kwargs["user"])
        calls.append(user)
        if len(calls) == 1:
            parsed = FitFields(
                score=80,
                matches=[AspectMatch(aspect_index=0, brag_doc_id="missing", similarity=0.9)],
            )
        else:
            parsed = FitFields(
                score=80,
                matches=[AspectMatch(aspect_index=0, brag_doc_id="doc-1", similarity=0.9)],
            )
        return parsed, None

    monkeypatch.setattr("jobhunt.fit.claude.structured_call", invoke)
    result = ClaudeFitScorer(prompt_version="v2").fit(
        [BragDoc(id="doc-1", text="Built APIs")],
        "- Build APIs for the billing service today",
    )
    assert len(calls) == 2
    assert "missing" in calls[1]
    assert result.score == 80.0
    assert result.top_docs[0].brag_doc_id == "doc-1"


def test_fit_stops_after_the_default_three_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def invoke(**_kwargs: object) -> tuple[FitFields, None]:
        calls["n"] += 1
        return (
            FitFields(
                score=80,
                matches=[AspectMatch(aspect_index=0, brag_doc_id="missing", similarity=0.9)],
            ),
            None,
        )

    monkeypatch.setattr("jobhunt.fit.claude.structured_call", invoke)
    with pytest.raises(FitUnavailable):
        ClaudeFitScorer(prompt_version="v2").fit(
            [BragDoc(id="doc-1", text="Built APIs")],
            "- Build APIs for the billing service today",
        )
    assert calls["n"] == 4


def test_a_truncated_reply_names_the_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def invoke(**_kwargs: object) -> tuple[FitFields, None]:
        raise ClaudeTruncated("reply hit max_tokens at 4096 tokens")

    monkeypatch.setattr("jobhunt.fit.claude.structured_call", invoke)
    with pytest.raises(FitUnavailable, match="max_tokens"):
        ClaudeFitScorer(prompt_version="v2").fit(
            [BragDoc(id="doc-1", text="Built APIs")],
            "- Build APIs for the billing service today",
        )
