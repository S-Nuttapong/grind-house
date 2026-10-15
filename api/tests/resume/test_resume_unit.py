"""Gate, filler order, tool hooks, and the Haiku price table. No database."""

from decimal import Decimal
from pathlib import Path

import pytest
from jobhunt.composition import require_on_machine
from jobhunt.fit.base import BragDoc
from jobhunt.fit.fake import FakeFitScorer
from jobhunt.resume.filler import rank_filler
from jobhunt.resume.gate import evaluate
from jobhunt.resume.hooks import deny_reason
from jobhunt.resume.pricing import estimate
from jobhunt.resume.sdk import ClaudeSdkWriter

_JOB = "- Built React services for payments\n- TypeScript services for the web app"
_REACT = "Built React services for payments"
_KAFKA = "TypeScript services for the web app"


def _resume(*bullets: dict[str, object]) -> dict[str, object]:
    return {"experience": [{"roles": [{"bullets": list(bullets)}]}]}


def test_gate_scores_only_shortlist_bullets() -> None:
    model = FakeFitScorer()
    shortlist_only = model.fit([BragDoc(id="BB-1", text=_REACT)], _JOB)
    result = evaluate(
        model,
        _JOB,
        _resume(
            {"text": _REACT, "src": ["BB-1"]},
            {"text": _KAFKA, "src": ["BB-9"]},
        ),
        shortlist_ids={"BB-1"},
        covered_aspects=[_REACT],
        baseline_score=shortlist_only.score,
        baseline_model_id="fake/v1",
    )
    assert result.passed
    assert result.resume_score == shortlist_only.score
    assert result.resume_coverage == shortlist_only.coverage
    assert result.extra_coverage > 0
    assert result.lost_aspects == []


def test_gate_reports_a_lost_requirement_and_ignores_a_different_model() -> None:
    model = FakeFitScorer()
    lost = evaluate(
        model,
        _JOB,
        _resume({"text": _REACT, "src": ["BB-1"]}),
        shortlist_ids={"BB-1"},
        covered_aspects=[_REACT, _KAFKA],
        baseline_score=0,
        baseline_model_id="fake/v1",
    )
    assert not lost.passed
    assert lost.lost_aspects == [_KAFKA]
    assert any("Lost requirement" in line for line in lost.feedback)

    skipped = evaluate(
        model,
        _JOB,
        _resume({"text": "unrelated", "src": ["BB-1"]}),
        shortlist_ids={"BB-1"},
        covered_aspects=[_KAFKA],
        baseline_score=99,
        baseline_model_id="qwen3",
    )
    assert skipped.passed and skipped.skipped


def test_filler_ranks_by_impact_then_similarity() -> None:
    docs = [
        BragDoc(id="profile", text=_REACT),
        BragDoc(id="BB-1", text=_REACT),
        BragDoc(id="low", text=_KAFKA),
        BragDoc(id="high-weak", text="Wrote notes"),
        BragDoc(id="high-strong", text=_KAFKA),
        BragDoc(id="unrated", text=_KAFKA),
    ]
    ranked = rank_filler(
        FakeFitScorer(),
        docs,
        {"BB-1"},
        {"low": 1, "high-weak": 5, "high-strong": 5, "unrated": None},
        _JOB,
    )
    assert [doc.id for doc in ranked] == ["high-strong", "high-weak", "low", "unrated"]


def test_hook_allows_kit_scripts_and_denies_everything_else(tmp_path: Path) -> None:
    workdir = tmp_path / "work"
    kit = tmp_path / "kit"
    workdir.mkdir()
    kit.mkdir()
    assert deny_reason("Write", {"file_path": "resume.json"}, workdir, kit) is None
    assert deny_reason("Write", {"file_path": "../escape.txt"}, workdir, kit) is not None
    render = deny_reason("Bash", {"command": f"python {kit / 'render_resume.py'}"}, workdir, kit)
    lint = deny_reason("Bash", {"command": f"python3 {kit / 'lint_resume.py'}"}, workdir, kit)
    assert render is None
    assert lint is None
    assert deny_reason("Bash", {"command": "python /tmp/other.py"}, workdir, kit) is not None
    assert deny_reason("Bash", {"command": "rm -rf /"}, workdir, kit) is not None
    assert deny_reason("Read", {"file_path": "/etc/hosts"}, workdir, kit) is None


def test_offsite_writer_requires_the_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JOBHUNT_ALLOW_OFFSITE", raising=False)
    with pytest.raises(ValueError, match="JOBHUNT_ALLOW_OFFSITE"):
        require_on_machine(ClaudeSdkWriter(), "resume writer")
    monkeypatch.setenv("JOBHUNT_ALLOW_OFFSITE", "1")
    require_on_machine(ClaudeSdkWriter(), "resume writer")


def test_pricing_uses_short_and_long_context_rates() -> None:
    short = estimate(
        "claude-haiku-5-5",
        input_tokens=1_000,
        output_tokens=2_000,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )
    assert short == Decimal("0.001100")
    opus = estimate(
        "claude-opus-5-5",
        input_tokens=1_000,
        output_tokens=2_000,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )
    assert opus == Decimal("0.044000")
    long = estimate(
        "other",
        input_tokens=200_000,
        output_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )
    assert long == Decimal("0.100000")
