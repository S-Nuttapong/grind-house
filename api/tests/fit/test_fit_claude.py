"""Claude fit mapping and contract. No network."""

from jobhunt.fit.base import BragDoc, DocMatch, FitResult
from jobhunt.fit.claude import AspectMatch, FitFields, result_from_fields
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
