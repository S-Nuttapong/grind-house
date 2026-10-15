"""Claude v3 scores from evidence: aspect cleanup, thin check, grounding, F-score. No network."""

import random

import pytest
from jobhunt.fit.base import BragDoc
from jobhunt.fit.claude import (
    AspectMatch,
    ClaudeFitScorer,
    MatchFields,
    clean_aspects,
    evidence_result,
    evidence_score,
    ground_matrix,
)

_THREE = (
    "- Build React interfaces for the billing product\n"
    "- Own TypeScript services end to end\n"
    "- Mentor engineers through code review\n"
)


def _no_call(**_kwargs: object) -> object:
    raise AssertionError("Claude must not be called")


def _best(n: int, *values: float) -> list[float]:
    return [*values, *([0.0] * (n - len(values)))]


@pytest.mark.parametrize(
    ("best", "expected"),
    [
        (_best(10, 0.95), 15.4),
        ([0.55] * 10, 11.4),
        ([0.70] * 10, 45.5),
        (_best(10, *([0.9] * 7)), 73.7),
        ([0.90] * 10, 90.9),
    ],
)
def test_worked_examples(best: list[float], expected: float) -> None:
    assert evidence_score(best) == pytest.approx(expected, abs=0.1)


@pytest.mark.parametrize("n", range(3, 51))
def test_one_matched_requirement_never_scores_above_33(n: int) -> None:
    for similarity in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        assert evidence_score(_best(n, similarity)) <= 33.4


def test_eighty_or_more_needs_evidence_on_two_thirds_of_n_plus_two() -> None:
    rng = random.Random(7)
    for _draw in range(5000):
        n = rng.randint(3, 30)
        best = [rng.choice([0.0, 0.5, 0.7, 0.85, 0.9, 1.0]) for _ in range(n)]
        if evidence_score(best) >= 80:
            credit = sum(min(1.0, max(0.0, (s - 0.5) / 0.4)) for s in best)
            assert credit >= 2 * (n + 2) / 3 - 1e-9


def test_weak_matches_everywhere_score_zero() -> None:
    assert evidence_score([0.5] * 12) == 0.0
    assert evidence_score([0.3] * 12) == 0.0


def test_score_is_monotonic_order_free_and_bounded() -> None:
    rng = random.Random(3)
    for _draw in range(500):
        best = [rng.random() for _ in range(rng.randint(3, 15))]
        score = evidence_score(best)
        assert 0.0 <= score <= 100.0
        assert evidence_score(list(reversed(best))) == score
        index = rng.randrange(len(best))
        raised = [*best]
        raised[index] = min(1.0, raised[index] + 0.1)
        assert evidence_score(raised) >= score


def test_link_benefit_and_eeo_bullets_are_not_requirements() -> None:
    description = (
        "- Build React interfaces for the billing product\n"
        "- [Flexible Paid Time Off](https://example.com/pto)\n"
        "- Competitive salary and equity compensation\n"
        "- We are an equal opportunity employer\n"
        "- Own TypeScript services end to end\n"
    )
    assert clean_aspects(description) == [
        "Build React interfaces for the billing product",
        "Own TypeScript services end to end",
    ]


def test_fewer_than_three_requirements_scores_zero_without_calling_claude(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("jobhunt.fit.claude.structured_call", _no_call)
    docs = [BragDoc(id="doc-1", text="Built React apps")]
    two = "- Build React interfaces for billing\n- Own TypeScript services end to end\n"
    padded = two + "- [Benefits](https://example.com)\n- Great health insurance and perks\n"
    for description in (two, padded, "Software Engineer"):
        result = ClaudeFitScorer().fit(docs, description)
        assert result.score == 0.0
        assert result.top_docs == []


def test_v3_score_comes_from_matches_not_from_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def invoke(**_kwargs: object) -> tuple[MatchFields, None]:
        return MatchFields(
            matches=[AspectMatch(aspect_index=0, brag_doc_id="doc-1", similarity=0.95)]
        ), None

    monkeypatch.setattr("jobhunt.fit.claude.structured_call", invoke)
    docs = [BragDoc(id="doc-1", text="Built React apps")]
    result = ClaudeFitScorer().fit(docs, _THREE)
    assert result.score == pytest.approx(33.3, abs=0.1)
    assert result.gaps == [
        "Own TypeScript services end to end",
        "Mentor engineers through code review",
    ]


def test_gaps_are_exactly_the_zero_credit_requirements() -> None:
    aspects = ["Build React interfaces", "Own APIs end to end", "Mentor engineers"]
    docs = [BragDoc(id="doc-1", text="Built React apps"), BragDoc(id="doc-2", text="Mentored")]
    parsed = MatchFields(
        matches=[
            AspectMatch(aspect_index=0, brag_doc_id="doc-1", similarity=0.9),
            AspectMatch(aspect_index=1, brag_doc_id="doc-1", similarity=0.5),
            AspectMatch(aspect_index=2, brag_doc_id="doc-2", similarity=0.7),
        ]
    )
    result = evidence_result(parsed, docs, aspects)
    assert result.gaps == ["Own APIs end to end"]
    assert evidence_result(parsed, docs, aspects) == result


def test_a_named_technology_needs_a_doc_that_mentions_it() -> None:
    aspects = ["Strong Ruby on Rails experience", "Build React interfaces", "Mentor engineers"]
    docs = [BragDoc(id="doc-1", text="Built React apps and mentored engineers")]
    grounded = ground_matrix([[0.9, 0.9, 0.9]], docs, aspects)
    assert grounded == [[0.0, 0.9, 0.9]]


def test_one_doc_keeps_only_its_top_matches() -> None:
    aspects = [f"Requirement number {index}" for index in range(9)]
    docs = [BragDoc(id=f"doc-{index}", text="general story") for index in range(3)]
    row = [0.9, 0.8, 0.95, 0.7, 0.85, 0.6, 0.75, 0.65, 0.55]
    grounded = ground_matrix([row, [0.0] * 9, [0.0] * 9], docs, aspects)
    assert grounded[0] == [0.9, 0.0, 0.95, 0.0, 0.85, 0.0, 0.0, 0.0, 0.0]


def test_a_single_doc_may_cover_more_than_three_requirements() -> None:
    aspects = [f"Requirement number {index}" for index in range(6)]
    docs = [BragDoc(id="resume:1#1", text="whole resume")]
    grounded = ground_matrix([[0.9] * 6], docs, aspects)
    assert grounded == [[0.9] * 6]
