"""Sampling, blinding, and judge math. No database and no model calls."""

from decimal import Decimal

import pytest
from jobhunt.core.claude import CallMeta
from jobhunt.fit.base import BragDoc, FitResult, FitUnavailable
from jobhunt.fit.benchmark import (
    _FITS_SQL,
    _MATCHES_SQL,
    LOW_CONFIDENCE,
    OPUS_JSON,
    SOL_JSON,
    BenchmarkError,
    CandidateOutcome,
    PopulationJob,
    QueueCase,
    assert_frozen,
    blind_letters,
    build_payload,
    judge_metrics,
    parse_judge_review,
    render_raw_markdown,
    render_report,
    replay_report,
    review_queue,
    run_candidate,
    stratified_sample,
    wilson_interval,
    write_run,
)
from jobhunt.fit.claude import AspectMatch, ClaudeFitScorer, FitFields


def _population(job_id: int, score: float) -> PopulationJob:
    return PopulationJob(
        job_id=job_id,
        title=f"Role {job_id}",
        scored_text=f"- Deliver work item {job_id} for the team",
        score=score,
        raw=score / 100,
        coverage=0.4,
        gaps=(),
        matches=(("doc-1", "Deliver work", 0.8),),
    )


def _case(
    job_id: int,
    *,
    opus: str | None = "A",
    sol: str | None = "A",
    opus_confidence: float = 0.9,
    sol_confidence: float = 0.9,
    baseline_tier: str = "low",
    candidate_tier: str | None = "low",
    score_delta: float | None = 0.0,
) -> QueueCase:
    return QueueCase(
        job_id=job_id,
        opus_preference=opus,
        sol_preference=sol,
        opus_confidence=opus_confidence,
        sol_confidence=sol_confidence,
        baseline_tier=baseline_tier,
        candidate_tier=candidate_tier,
        score_delta=score_delta,
    )


def test_stratified_sample_fills_a_short_tier_and_stays_stable() -> None:
    jobs = (
        [_population(job_id, 10) for job_id in range(1, 11)]
        + [_population(job_id, 50) for job_id in range(11, 26)]
        + [_population(job_id, 70) for job_id in range(26, 41)]
        + [_population(job_id, 90) for job_id in range(41, 71)]
    )
    picked = stratified_sample(jobs, n=60, seed=7)
    again = stratified_sample(jobs, n=60, seed=7)
    other = stratified_sample(jobs, n=60, seed=8)
    assert [job.job_id for job in picked] == [job.job_id for job in again]
    assert [job.job_id for job in picked] == sorted(job.job_id for job in picked)
    assert len(picked) == 60
    assert sum(1 for job in picked if job.tier == "low") == 10
    assert sum(1 for job in picked if job.tier == "strong") == 20
    assert {job.job_id for job in picked} != {job.job_id for job in other}


def test_stratified_sample_returns_every_job_when_the_pool_is_smaller() -> None:
    jobs = [_population(job_id, score) for job_id, score in enumerate((10, 50, 70, 90), start=1)]
    picked = stratified_sample(jobs, n=60, seed=1)
    assert {job.job_id for job in picked} == {1, 2, 3, 4}


def test_stratified_sample_rejects_a_negative_size() -> None:
    with pytest.raises(BenchmarkError):
        stratified_sample([], n=-1, seed=1)


def test_blind_letters_are_deterministic_and_cover_both_sides() -> None:
    first = blind_letters(4, 7)
    assert first == blind_letters(4, 7)
    assert {first["A"], first["B"]} == {"baseline", "candidate"}
    sides = {blind_letters(job_id, 7)["A"] for job_id in range(30)}
    assert sides == {"baseline", "candidate"}


def test_wilson_interval_for_no_trials_and_a_zero_success() -> None:
    assert wilson_interval(0, 0) is None
    lower, upper = wilson_interval(0, 1)
    assert lower == 0
    assert round(upper, 5) == 0.79346


def test_review_queue_orders_disagreement_then_doubt_then_tier_then_audit() -> None:
    cases = [
        _case(1),
        _case(2, sol="B"),
        _case(3, opus_confidence=LOW_CONFIDENCE - 0.1),
        _case(4, baseline_tier="low", candidate_tier="strong", score_delta=40),
    ]
    assert review_queue(cases, limit=4, seed=3) == [2, 3, 4, 1]
    assert review_queue(cases, limit=3, seed=3) == [2, 3, 4]


def test_review_queue_caps_disagreements_and_keeps_the_audit_stable() -> None:
    disagreements = [_case(job_id, sol="B") for job_id in range(25)]
    assert review_queue(disagreements, limit=20, seed=1) == list(range(20))
    agreements = [_case(job_id) for job_id in range(30)]
    assert review_queue(agreements, limit=5, seed=11) == review_queue(agreements, limit=5, seed=11)
    assert review_queue(agreements, limit=5, seed=11) != review_queue(agreements, limit=5, seed=12)


def test_a_missing_judgment_is_queued_before_an_agreement() -> None:
    cases = [_case(1), _case(2, opus=None)]
    assert review_queue(cases, limit=1, seed=1) == [2]


def test_parse_judge_review_rejects_a_bad_preference_and_a_duplicate() -> None:
    with pytest.raises(BenchmarkError):
        parse_judge_review(
            {
                "recommendation": "A",
                "summary": "ok",
                "themes": [],
                "limitations": [],
                "jobs": [
                    {
                        "job_id": 1,
                        "preference": "C",
                        "confidence": 0.5,
                        "rating": 3,
                        "evidence": "no",
                    }
                ],
            }
        )
    with pytest.raises(BenchmarkError):
        parse_judge_review(
            {
                "recommendation": "tie",
                "summary": "ok",
                "themes": [],
                "limitations": [],
                "jobs": [
                    _judgment(1),
                    _judgment(1),
                ],
            }
        )


def test_judge_metrics_keeps_ties_out_of_the_win_rate() -> None:
    jobs = [_raw_job(1, baseline=80, candidate=40), _raw_job(2, baseline=20, candidate=90)]
    identity = {
        "jobs": {
            "1": {"A": "baseline", "B": "candidate"},
            "2": {"A": "candidate", "B": "baseline"},
        }
    }
    tied = parse_judge_review(
        _review([_judgment(1, preference="tie"), _judgment(2, preference="tie")])
    )
    tied_metrics = judge_metrics(jobs, identity, tied)
    assert tied_metrics["decisive"] == 0
    assert tied_metrics["candidate_win_rate"] is None
    assert tied_metrics["wilson95"] is None

    split = parse_judge_review(
        _review(
            [
                _judgment(1, preference="B", expected_docs=["doc-1"]),
                _judgment(2, preference="B"),
            ]
        )
    )
    metrics = judge_metrics(jobs, identity, split)
    assert metrics["candidate_wins"] == 1
    assert metrics["decisive"] == 2
    assert metrics["candidate_win_rate"] == 0.5
    assert metrics["missing"] == 0
    assert metrics["hit_at_10_candidate"] == 1
    assert metrics["spearman_candidate"] is not None


def test_blinded_packet_hides_model_ids_and_the_freeze_is_immutable(tmp_path) -> None:
    raw, identity, packet = _bundle()
    digest = write_run(tmp_path, raw=raw, identity=identity, packet=packet)
    assert assert_frozen(tmp_path) == digest
    encoded = (tmp_path / "blinded" / "packet.json").read_text(encoding="utf-8")
    assert "qwen3-embedding-0.6b/v1" not in encoded
    assert "claude-haiku-5-5/v1" not in encoded
    assert "baseline" not in encoded
    assert packet["jobs"][0]["A"]["score"] in {80.0, 55.0}
    markdown = render_raw_markdown(raw)
    assert "Deliver work item 1 for the team" not in markdown
    assert "qwen3-embedding-0.6b/v1" in markdown
    with pytest.raises(BenchmarkError):
        write_run(tmp_path, raw=raw, identity=identity, packet=packet)


def test_report_prints_judges_separately(tmp_path) -> None:
    raw, identity, packet = _bundle()
    write_run(tmp_path, raw=raw, identity=identity, packet=packet)
    review = _review([_judgment(1, preference="A")])
    (tmp_path / OPUS_JSON).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / OPUS_JSON).write_text(_json(review), encoding="utf-8")
    (tmp_path / SOL_JSON).write_text(
        _json(_review([_judgment(1, preference="B")], recommendation="B")),
        encoding="utf-8",
    )
    report = render_report(tmp_path)
    assert "opus: recommendation A" in report
    assert "sol: recommendation B" in report
    assert "Judges are reported separately." in report
    assert "human queue: 1" in report


def test_candidate_scoring_uses_the_existing_scorer_and_restores_the_client() -> None:
    from jobhunt.fit import claude as claude_fit

    def invoke(**_kwargs: object) -> tuple[FitFields, CallMeta]:
        return (
            FitFields(
                score=64,
                matches=[AspectMatch(aspect_index=0, brag_doc_id="doc-1", similarity=0.7)],
            ),
            CallMeta(
                model="claude-haiku-5-5",
                input_tokens=12,
                output_tokens=4,
                cache_read_tokens=0,
                cache_write_tokens=0,
                cost_usd=Decimal("0.00001200"),
            ),
        )

    original = claude_fit.structured_call
    outcomes = run_candidate(
        ClaudeFitScorer(prompt_version="v2"),
        [BragDoc(id="doc-1", text="Deliver work item 1 for the team")],
        [_population(1, 10)],
        invoke_model=invoke,
    )
    assert claude_fit.structured_call is original
    assert outcomes[0].result is not None
    assert outcomes[0].result.score == 64
    assert outcomes[0].matches == ((0, "doc-1", 0.7),)
    assert outcomes[0].cost_usd == Decimal("0.00001200")
    assert outcomes[0].input_tokens == 12


def test_replay_uses_recorded_matches_and_skips_a_file_without_them(tmp_path) -> None:
    from pathlib import Path

    out = Path(tmp_path)
    (out / "reviews").mkdir()
    raw = {
        "docs": [{"id": "doc-1", "text": "Built React apps"}],
        "jobs": [
            {
                "job_id": 1,
                "scored_text": (
                    "- Build React interfaces for the billing product\n"
                    "- Own TypeScript services end to end\n"
                    "- Mentor engineers through code review\n"
                ),
                "candidate": {
                    "coverage": 0.9,
                    "matches": [
                        {"aspect_index": 0, "doc_id": "doc-1", "similarity": 0.95},
                    ],
                },
            }
        ],
    }
    (out / "raw.json").write_text(_json(raw), encoding="utf-8")
    (out / OPUS_JSON).write_text(
        _json({"jobs": [{"job_id": 1, "rating": 2}]}),
        encoding="utf-8",
    )
    (out / SOL_JSON).write_text(
        _json({"jobs": [{"job_id": 1, "rating": 2}]}),
        encoding="utf-8",
    )
    report = replay_report(out)
    assert report["missing_matches"] == 0
    assert report["replayed"] == 1
    assert report["fair_or_better_with_coverage_under_0_1"] == 0
    assert report["rated_4_or_5_in_low_opus"] == []
    assert report["spearman_opus"] is None

    bare = Path(tmp_path) / "old"
    bare.mkdir()
    (bare / "raw.json").write_text(
        _json(
            {
                "docs": [],
                "jobs": [{"job_id": 9, "scored_text": "x", "candidate": {"score": 80}}],
            }
        ),
        encoding="utf-8",
    )
    assert replay_report(bare)["missing_matches"] == 1


def test_a_failed_score_stays_on_that_job_and_queries_do_not_write() -> None:
    class Unavailable:
        def fit(self, docs: list[BragDoc], job_description: str) -> FitResult:
            raise FitUnavailable("down")

    outcomes = run_candidate(Unavailable(), [], [_population(1, 10)])
    assert outcomes[0].error == "down"
    assert outcomes[0].result is None
    raw, _identity, _packet = build_payload(
        seed=1,
        mode="bank",
        source_hash="abc",
        baseline_model_id="qwen3-embedding-0.6b/v1",
        candidate_model_id="claude-haiku-5-5/v1",
        docs=[],
        selected=[_population(1, 10)],
        outcomes=[
            CandidateOutcome(
                job_id=1,
                result=None,
                error="down",
                latency_ms=5,
                cost_usd=Decimal("0.10"),
                input_tokens=0,
                output_tokens=0,
            )
        ],
    )
    assert raw["jobs"][0]["candidate"] is None
    assert raw["summary"]["failures"] == 1
    assert raw["summary"]["cost_usd"] == "0.10"
    folded = f"{_FITS_SQL}\n{_MATCHES_SQL}".lower()
    assert "insert" not in folded
    assert "update" not in folded
    assert "delete" not in folded


def _bundle() -> tuple[dict, dict, dict]:
    outcome = CandidateOutcome(
        job_id=1,
        result=FitResult(score=55, raw=0.5, coverage=0.25, top_docs=[], gaps=["gap"]),
        error=None,
        latency_ms=15,
        cost_usd=Decimal("0.02"),
        input_tokens=3,
        output_tokens=2,
    )
    return build_payload(
        seed=5,
        mode="bank",
        source_hash="source",
        baseline_model_id="qwen3-embedding-0.6b/v1",
        candidate_model_id="claude-haiku-5-5/v1",
        docs=[BragDoc(id="doc-1", text="Deliver work item 1 for the team")],
        selected=[_population(1, 80)],
        outcomes=[outcome],
    )


def _raw_job(job_id: int, *, baseline: float, candidate: float) -> dict:
    return {
        "job_id": job_id,
        "baseline": {
            "score": baseline,
            "tier": "good",
            "top_docs": [{"doc_id": "doc-1"}],
        },
        "candidate": {
            "score": candidate,
            "tier": "fair",
            "top_docs": [{"doc_id": "doc-1"}],
        },
    }


def _judgment(
    job_id: int, *, preference: str = "A", expected_docs: list[str] | None = None
) -> dict:
    return {
        "job_id": job_id,
        "preference": preference,
        "confidence": 0.8,
        "rating": 4 if job_id == 1 else 2,
        "evidence": "the cited doc covers the aspect" if preference != "tie" else "equal",
        "expected_docs": expected_docs or [],
    }


def _review(jobs: list[dict], *, recommendation: str = "A") -> dict:
    return {
        "recommendation": recommendation,
        "summary": "A is more faithful on the decisive jobs.",
        "themes": ["unsupported scores"],
        "limitations": ["one sample"],
        "jobs": jobs,
    }


def _json(payload: dict) -> str:
    import json

    return json.dumps(payload)
