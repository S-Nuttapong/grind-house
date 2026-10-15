"""Prompt versions, gold labels, and the optimizer. No network."""

import json
import random
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from jobhunt.core.claude import CallMeta
from jobhunt.fit.base import BragDoc
from jobhunt.fit.claude import ClaudeFitScorer, FitFields, system_prompt
from jobhunt.fit.eval import (
    BootstrapJob,
    FitReport,
    objective,
    paired_bootstrap,
    precision_at_k,
    recall_at_k,
    spearman,
)
from jobhunt.fit.optimize import (
    STUDENT_MODEL,
    TEACHER_MODEL,
    VersionScore,
    accept_candidate,
    decide_prompt,
    install_v2,
    leak_reasons,
    optimize_prompt,
)
from jobhunt.fit.roles import (
    ROLE_SEED,
    GoldError,
    evaluate_prompts,
    label_fit_gold,
    load_fit_gold,
    split_fit_jobs,
)

_STRONG = "This is a strong role for a senior engineer. Build APIs for the billing service today."
_WEAK = "This is a weak role for a career change. Build APIs for the billing service today."
_OTHER = "This is a different role in another field. Build APIs for the billing service today."


def test_precision_and_recall_are_shares_of_picks_and_expected() -> None:
    chosen = [["a", "b"], ["c"]]
    expected = [["a"], ["c", "d"]]
    assert precision_at_k(chosen, expected, 10) == pytest.approx(2 / 3)
    assert recall_at_k(chosen, expected, 10) == pytest.approx(2 / 3)
    assert precision_at_k([[], []], [["a"], []], 10) is None
    assert recall_at_k([["a"], []], [[], []], 10) is None


def test_bootstrap_is_seeded_paired_and_clears_a_real_gain() -> None:
    left = [
        BootstrapJob(score=10, rating=1, picks=("a",), gold_docs=("a",)),
        BootstrapJob(score=90, rating=5, picks=("b",), gold_docs=()),
    ]
    right = [
        BootstrapJob(score=90, rating=1, picks=(), gold_docs=("a",)),
        BootstrapJob(score=10, rating=5, picks=("b",), gold_docs=("b",)),
    ]
    first = paired_bootstrap(left, right, seed=7, resamples=20)
    assert first == paired_bootstrap(left, right, seed=7, resamples=20)
    rng = random.Random(7)
    deltas: list[float] = []
    for _draw in range(20):
        indexes = [rng.randrange(2) for _index in range(2)]
        delta = _objective_delta(
            [right[index] for index in indexes], [left[index] for index in indexes]
        )
        if delta is not None:
            deltas.append(delta)
    assert first["objective"].mean == pytest.approx(sum(deltas) / len(deltas))

    ratings = [1, 2, 3, 4, 5, 1, 2, 3]
    weak = [_row(rating * 20, ("no",), ("yes",), rating) for rating in ratings]
    strong = [_row(rating * 20, ("yes",), ("yes",), rating) for rating in ratings]
    gain = paired_bootstrap(weak, strong, seed=2, resamples=200)
    assert gain["objective"].low > 0

    same = paired_bootstrap(strong, strong, seed=3, resamples=50)
    assert same["objective"].low <= 0 <= same["objective"].high


def test_bootstrap_rejects_unpaired_lengths() -> None:
    job = BootstrapJob(score=1, rating=1, picks=(), gold_docs=())
    with pytest.raises(ValueError, match="same jobs"):
        paired_bootstrap([job], [job, job], seed=1, resamples=1)


def test_v1_system_text_is_unchanged() -> None:
    text = system_prompt([BragDoc(id="BB-001", text="Title\nbody")], version="v1")
    assert text == (
        "Score how well the brag docs cover the job aspects in the user message.\n"
        "score is 0 to 100.\n"
        "Each match has aspect_index (0-based into the user list), brag_doc_id copied\n"
        "from the list below, and similarity from 0 to 1.\n"
        "Include a match only when that doc covers that aspect.\n"
        "Do not invent a document id.\n"
        "\n"
        "Brag docs:\n"
        "id=BB-001\n"
        "Title\n"
        "body"
    )
    assert "<doc" not in text


def test_prompt_version_sets_the_model_id_and_layout() -> None:
    assert ClaudeFitScorer().model_id == "claude-haiku-5-5/v3"
    v2 = ClaudeFitScorer(prompt_version="v2")
    assert v2.model_id == "claude-haiku-5-5/v2"
    text = system_prompt([BragDoc(id="BB-001", text="Title\nbody")], version="v2")
    assert text.startswith('<doc id="BB-001">')
    assert text.index("</doc>") < text.index("85 to 100")
    candidate = ClaudeFitScorer(prompt_version="cand-r2", rubric="Custom rules here.")
    assert candidate.model_id == "claude-haiku-5-5/cand-r2"
    custom = system_prompt(
        [BragDoc(id="BB-001", text="Title")], version="cand-r2", rubric="Custom rules here."
    )
    assert custom.endswith("Custom rules here.")
    with pytest.raises(ValueError, match="v1 does not take"):
        ClaudeFitScorer(prompt_version="v1", rubric="nope")


def test_student_scorer_calls_the_student_model(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def invoke(**kwargs: Any) -> tuple[FitFields, CallMeta]:
        seen.append(str(kwargs["model"]))
        return FitFields(score=10, matches=[]), _meta(str(kwargs["model"]))

    monkeypatch.setattr("jobhunt.fit.claude.structured_call", invoke)
    ClaudeFitScorer(prompt_version="v2").fit(
        [BragDoc(id="BB-001", text="Built APIs")],
        "- Build APIs for the billing service today",
    )
    assert seen == [STUDENT_MODEL]


def test_split_is_stable_60_40() -> None:
    ids = list(range(100))
    assert split_fit_jobs(ids, seed=ROLE_SEED) == split_fit_jobs(ids, seed=ROLE_SEED)
    dev, test = split_fit_jobs(ids, seed=ROLE_SEED)
    assert len(dev) == 60
    assert len(test) == 40
    assert set(dev).isdisjoint(test)
    assert set(dev) | set(test) == set(ids)


def test_gold_loader_rejects_a_hand_written_file(tmp_path: Path) -> None:
    path = tmp_path / "gold.yaml"
    _write_gold(path, [(1, 4, ["BB-001"])])
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    payload["jobs"][0].pop("call")
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(GoldError, match="call record"):
        load_fit_gold(path, {"BB-001"}, {1})

    _write_gold(path, [(1, 4, ["BB-001"])])
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    payload["jobs"][0]["call"]["model"] = "claude-haiku-5-5"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(GoldError, match="not the teacher"):
        load_fit_gold(path, {"BB-001"}, {1})

    _write_gold(path, [(1, 4, ["BB-999"])])
    with pytest.raises(GoldError, match="unknown"):
        load_fit_gold(path, {"BB-001"}, {1})

    _write_gold(path, [(1, 4, ["BB-001"])])
    with pytest.raises(GoldError, match="missing"):
        load_fit_gold(path, {"BB-001"}, {1, 2})


def test_labeler_uses_the_teacher_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = tmp_path / "sample.json"
    gold = tmp_path / "gold.yaml"
    _write_sample(sample, [1, 2])
    _write_gold(gold, [(1, 4, ["BB-001"])])
    seen: list[str] = []

    def invoke(**kwargs: Any) -> tuple[Any, CallMeta]:
        seen.append(str(kwargs["model"]))
        output = kwargs["output"]
        if output.__name__ == "_Ping":
            return output(ok=True), _meta(TEACHER_MODEL)
        return output(rating=3, docs=["BB-001"], reason="Use the story."), _meta(TEACHER_MODEL)

    monkeypatch.setattr("jobhunt.core.claude.structured_call", invoke)
    label_fit_gold(sample, gold, budget_usd=Decimal("15"))
    assert seen[0] == TEACHER_MODEL
    assert all(model == TEACHER_MODEL for model in seen)
    assert len(seen) == 2
    loaded = load_fit_gold(gold, {"BB-001"}, {1, 2})
    assert [job.job_id for job in loaded] == [1, 2]


def test_labeler_rejects_an_unknown_story(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sample = tmp_path / "sample.json"
    gold = tmp_path / "gold.yaml"
    _write_sample(sample, [1])

    def invoke(**kwargs: Any) -> tuple[Any, CallMeta]:
        output = kwargs["output"]
        if output.__name__ == "_Ping":
            return output(ok=True), _meta(TEACHER_MODEL)
        return output(rating=9, docs=["BB-999"], reason=""), _meta(TEACHER_MODEL)

    monkeypatch.setattr("jobhunt.core.claude.structured_call", invoke)
    with pytest.raises(GoldError, match="unknown"):
        label_fit_gold(sample, gold, budget_usd=Decimal("15"))


def test_leak_guard_and_accept_margin() -> None:
    assert leak_reasons("Use BB-022 for this", ["GitLab"])
    assert leak_reasons("GitLab likes Java", ["GitLab"])
    assert leak_reasons("gitlab likes Java", ["GitLab"])
    assert leak_reasons("x" * 4001, ["GitLab"])
    assert leak_reasons("Match only real requirements.", ["GitLab"]) == []
    assert accept_candidate(0.80, 0.75, []) is True
    assert accept_candidate(0.76, 0.75, []) is False
    assert accept_candidate(0.90, 0.75, ["retest sd above 5"]) is False


def test_optimizer_keeps_a_better_rubric_and_hides_the_test_half(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample, gold = _loop_files(tmp_path)
    users: list[str] = []
    monkeypatch.setenv("JOBHUNT_ALLOW_OFFSITE", "1")
    monkeypatch.setattr(
        "jobhunt.core.claude.structured_call",
        _teacher(users, "candidate-better\nMatch requirements."),
    )
    monkeypatch.setattr("jobhunt.fit.claude.structured_call", _student())
    dev, test = split_fit_jobs([1, 2, 3, 4], seed=ROLE_SEED, dev_n=2)
    result = optimize_prompt(sample, gold, tmp_path / "opt", rounds=1, patience=2, reps=2, dev_n=2)
    assert result["best"] == "cand-r1"
    assert "TestCo" not in users[0]
    for job_id in test:
        assert f"job {job_id}" not in users[0]
    for job_id in dev:
        assert f"job {job_id}" in users[0]


def test_optimizer_stops_on_patience_budget_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample, gold = _loop_files(tmp_path)
    monkeypatch.setenv("JOBHUNT_ALLOW_OFFSITE", "1")
    calls = {"teacher": 0}

    def teacher(**kwargs: Any) -> tuple[Any, CallMeta]:
        calls["teacher"] += 1
        output = kwargs["output"]
        return (
            output(rubric="Match only real requirements.", rationale="same"),
            _meta(TEACHER_MODEL),
        )

    monkeypatch.setattr("jobhunt.core.claude.structured_call", teacher)
    monkeypatch.setattr("jobhunt.fit.optimize.score_version", _flat_score)
    opt = tmp_path / "opt"
    opt.mkdir()
    (opt / "round-0.json").write_text(json.dumps(_seed_round()), encoding="utf-8")
    stopped = optimize_prompt(sample, gold, opt, rounds=5, patience=2, reps=1, dev_n=2)
    assert stopped["stopped"] == "patience"
    assert calls["teacher"] == 2
    assert json.loads((opt / "round-2.json").read_text(encoding="utf-8"))["streak"] == 2
    assert not (opt / "round-3.json").is_file()

    budget_dir = tmp_path / "budget"
    budget_dir.mkdir()
    (budget_dir / "round-0.json").write_text(json.dumps(_seed_round(cost="6.00")), encoding="utf-8")
    calls["teacher"] = 0
    stopped = optimize_prompt(sample, gold, budget_dir, rounds=5, patience=2, budget_usd=6, dev_n=2)
    assert stopped["stopped"] == "budget"
    assert calls["teacher"] == 0

    resume = tmp_path / "resume"
    resume.mkdir()
    (resume / "round-0.json").write_text(json.dumps(_seed_round(cost="0.10")), encoding="utf-8")
    (resume / "round-1.json").write_text(json.dumps(_proposal_round(1)), encoding="utf-8")
    calls["teacher"] = 0
    monkeypatch.setattr("jobhunt.fit.claude.structured_call", _student())
    monkeypatch.setattr(
        "jobhunt.core.claude.structured_call",
        _teacher([], "Match only real requirements."),
    )
    optimize_prompt(sample, gold, resume, rounds=2, patience=5, reps=1, dev_n=2)
    assert (resume / "round-2.json").is_file()


def test_install_v2_switches_the_default(tmp_path: Path) -> None:
    source = tmp_path / "claude.py"
    source.write_text(
        '_PROMPT_VERSION = "v2"\n# v3-rubric:start\n_V3_RUBRIC = "old"\n# v3-rubric:end\n',
        encoding="utf-8",
    )
    install_v2("score is 0 to 100.\n85 to 100 means a strong match.\nnew rubric", source)
    text = source.read_text(encoding="utf-8")
    assert '_PROMPT_VERSION = "v3"' in text
    assert "new rubric" in text
    assert "old" not in text
    assert "score is 0 to 100" not in text
    assert "85 to 100" not in text


def test_evaluate_prompts_scores_only_the_requested_half(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample, gold = _loop_files(tmp_path)
    seen: list[list[int]] = []

    def fake_score(
        _docs: Any, jobs: list[dict[str, Any]], _gold: Any, **kwargs: Any
    ) -> VersionScore:
        from jobhunt.fit.eval import FitReport

        seen.append([int(job["job_id"]) for job in jobs])
        return VersionScore(
            name=str(kwargs["name"]),
            prompt_version=str(kwargs["prompt_version"]),
            rubric=None,
            report=FitReport(0.2, None, None, None, 0.0, 0.0, 0.4, 0.4),
            jobs=[],
            failures=0,
            cost_usd=Decimal("0"),
        )

    monkeypatch.setattr("jobhunt.fit.optimize.score_version", fake_score)
    dest = tmp_path / "eval"
    evaluate_prompts(sample, gold, ["v1"], reps=1, half="dev", dest=dest, dev_n=2)
    dev, _test = split_fit_jobs([1, 2, 3, 4], seed=ROLE_SEED, dev_n=2)
    assert seen == [dev]
    assert (dest / "prompt-eval.json").is_file()


def _objective_delta(right: list[BootstrapJob], left: list[BootstrapJob]) -> float | None:
    first = _objective(left)
    second = _objective(right)
    if first is None or second is None:
        return None
    return second - first


def _objective(jobs: list[BootstrapJob]) -> float | None:
    precision = precision_at_k([job.picks for job in jobs], [job.gold_docs for job in jobs], 10)
    rho = spearman([job.score for job in jobs], [job.rating for job in jobs])
    return objective(precision, rho)


def _row(score: float, picks: tuple[str, ...], gold: tuple[str, ...], rating: int) -> BootstrapJob:
    return BootstrapJob(
        score=score,
        rating=float(rating),
        picks=picks,
        gold_docs=gold,
        scores=(score, score),
        order_delta=0.0,
    )


def _meta(model: str, cost: str = "0.01") -> CallMeta:
    return CallMeta(
        model=model,
        input_tokens=10,
        output_tokens=5,
        cache_read_tokens=0,
        cache_write_tokens=0,
        cost_usd=Decimal(cost),
    )


def _call() -> dict[str, Any]:
    return {
        "model": TEACHER_MODEL,
        "input_tokens": 1,
        "output_tokens": 1,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": "0.01",
    }


def _write_gold(path: Path, jobs: list[tuple[int, int, list[str]]]) -> None:
    entries = [
        {
            "job_id": job_id,
            "rating": rating,
            "docs": docs,
            "reason": "Fits.",
            "call": _call(),
        }
        for job_id, rating, docs in jobs
    ]
    path.write_text(
        yaml.safe_dump({"labeler": TEACHER_MODEL, "jobs": entries}, sort_keys=False),
        encoding="utf-8",
    )


def _write_sample(path: Path, job_ids: list[int]) -> None:
    dev: list[int] = []
    if len(job_ids) >= 2:
        dev, _test = split_fit_jobs(job_ids, seed=ROLE_SEED, dev_n=max(1, len(job_ids) // 2))
    jobs = []
    for job_id in job_ids:
        if dev and job_id == dev[0]:
            description = _STRONG
            company = "DevCo"
        elif job_id in dev:
            description = _WEAK
            company = "DevCo"
        else:
            description = f"TestCo. {_OTHER}"
            company = "TestCo"
        jobs.append(
            {
                "job_id": job_id,
                "title": "Engineer",
                "company": company,
                "description": description,
            }
        )
    path.write_text(
        json.dumps(
            {
                "seed": ROLE_SEED,
                "docs": [{"id": "BB-001", "title": "API", "text": "Built APIs for billing."}],
                "jobs": jobs,
            }
        ),
        encoding="utf-8",
    )


def _loop_files(tmp_path: Path) -> tuple[Path, Path]:
    sample = tmp_path / "sample.json"
    gold = tmp_path / "gold.yaml"
    _write_sample(sample, [1, 2, 3, 4])
    dev, _test = split_fit_jobs([1, 2, 3, 4], seed=ROLE_SEED, dev_n=2)
    rows = []
    for job_id in [1, 2, 3, 4]:
        rating = 5 if job_id == dev[0] else 1 if job_id in dev else 3
        docs = ["BB-001"] if rating >= 4 else []
        rows.append((job_id, rating, docs))
    _write_gold(gold, rows)
    return sample, gold


def _seed_round(cost: str = "0.10") -> dict[str, Any]:
    version = {
        "name": "v1",
        "prompt_version": "v1",
        "rubric": None,
        "objective": 0.5,
        "precision_at_10": 0.5,
        "spearman": 0.5,
        "retest_sd": 0,
        "order_delta": 0,
        "failures": 0,
        "cost_usd": cost,
        "jobs": [],
    }
    return {
        "round": 0,
        "kind": "seed",
        "versions": [version],
        "best_name": "v1",
        "best_prompt_version": "v1",
        "best_rubric": None,
        "best_objective": 0.5,
        "streak": 0,
        "kept": True,
        "cost_usd": cost,
    }


def _proposal_round(number: int) -> dict[str, Any]:
    return {
        "round": number,
        "kind": "proposal",
        "name": f"cand-r{number}",
        "rubric": "Match only real requirements.",
        "rationale": "shorter",
        "proposal_call": _call(),
        "rejected": [],
        "kept": False,
        "metrics": None,
        "jobs": [],
        "best_name": "v1",
        "best_prompt_version": "v1",
        "best_rubric": None,
        "best_objective": 0.5,
        "streak": 0,
        "scored": True,
        "cost_usd": "0.01",
    }


def test_repair_turns_a_leak_into_a_scored_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample, gold = _loop_files(tmp_path)
    calls = {"n": 0}
    systems: list[str] = []

    def teacher(**kwargs: Any) -> tuple[Any, CallMeta]:
        calls["n"] += 1
        systems.append(str(kwargs["system"]))
        rubric = "Use BB-001" if calls["n"] == 1 else "candidate-better\nMatch requirements."
        return kwargs["output"](rubric=rubric, rationale="fix"), _meta(TEACHER_MODEL)

    monkeypatch.setenv("JOBHUNT_ALLOW_OFFSITE", "1")
    monkeypatch.setattr("jobhunt.core.claude.structured_call", teacher)
    monkeypatch.setattr("jobhunt.fit.claude.structured_call", _student())
    opt = tmp_path / "opt"
    opt.mkdir()
    (opt / "round-0.json").write_text(json.dumps(_seed_round()), encoding="utf-8")
    result = optimize_prompt(sample, gold, opt, rounds=1, patience=2, reps=1, dev_n=2)
    row = json.loads((opt / "round-1.json").read_text(encoding="utf-8"))
    assert row["scored"] is True
    assert row["rejected"] == []
    assert result["scored_rounds"] == 1
    assert calls["n"] == 2
    assert "DevCo" in systems[0]
    assert "BB-001" in systems[0]
    assert "Spark" in systems[0]


def test_rejected_round_does_not_raise_the_patience_streak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample, gold = _loop_files(tmp_path)

    def teacher(**kwargs: Any) -> tuple[Any, CallMeta]:
        output = kwargs["output"]
        return output(rubric="Use BB-001 always", rationale="memorized"), _meta(TEACHER_MODEL)

    monkeypatch.setattr("jobhunt.core.claude.structured_call", teacher)
    opt = tmp_path / "opt"
    opt.mkdir()
    (opt / "round-0.json").write_text(json.dumps(_seed_round(cost="0")), encoding="utf-8")
    stopped = optimize_prompt(
        sample, gold, opt, rounds=5, patience=2, budget_usd=0.03, reps=1, dev_n=2
    )
    row = json.loads((opt / "round-1.json").read_text(encoding="utf-8"))
    assert row["scored"] is False
    assert row["streak"] == 0
    assert stopped["scored_rounds"] == 0
    assert stopped["stopped"] == "budget"
    assert not (opt / "round-2.json").is_file()


def test_decide_prompt_uses_the_fresh_test_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample, gold = _loop_files(tmp_path)
    fresh = tmp_path / "fresh.json"
    fresh_gold = tmp_path / "fresh.yaml"
    fresh.write_text(
        json.dumps(
            {
                "seed": 20261013,
                "docs": [{"id": "BB-001", "title": "API", "text": "Built APIs"}],
                "jobs": [
                    {
                        "job_id": 10,
                        "title": "Engineer",
                        "company": "NewCo",
                        "description": "Build APIs",
                    },
                    {
                        "job_id": 11,
                        "title": "Engineer",
                        "company": "NewCo",
                        "description": "Build APIs",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    _write_gold(fresh_gold, [(10, 3, ["BB-001"]), (11, 3, [])])
    dest = tmp_path / "opt"
    dest.mkdir()
    (dest / "round-0.json").write_text(json.dumps(_seed_round()), encoding="utf-8")
    seen: list[list[int]] = []

    def fake_score(
        _docs: Any, jobs: list[dict[str, Any]], _gold: Any, **kwargs: Any
    ) -> VersionScore:
        seen.append([int(job["job_id"]) for job in jobs])
        return _flat_score(**kwargs)

    monkeypatch.setattr("jobhunt.fit.optimize.score_version", fake_score)

    def refuse_install(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("v1 must stay")

    monkeypatch.setattr("jobhunt.fit.optimize.install_v2", refuse_install)
    decision = decide_prompt(sample, gold, dest, reps=1, test_sample=fresh, test_gold=fresh_gold)
    assert seen == [[10, 11], [10, 11]]
    assert decision["shipped"] is False


def _flat_score(*_args: Any, **kwargs: Any) -> VersionScore:
    return VersionScore(
        name=str(kwargs["name"]),
        prompt_version=str(kwargs["prompt_version"]),
        rubric=kwargs.get("rubric"),
        report=FitReport(0.0, None, None, None, 0.0, 0.0, 0.0, 0.0),
        jobs=[],
        failures=0,
        cost_usd=Decimal("0.01"),
    )


def _teacher(users: list[str], rubric: str) -> Any:
    def invoke(**kwargs: Any) -> tuple[Any, CallMeta]:
        assert kwargs["model"] == TEACHER_MODEL
        users.append(str(kwargs["user"]))
        return kwargs["output"](rubric=rubric, rationale="tighter"), _meta(TEACHER_MODEL)

    return invoke


def _student() -> Any:
    def invoke(**kwargs: Any) -> tuple[FitFields, CallMeta]:
        assert kwargs["model"] == STUDENT_MODEL
        user = str(kwargs["user"])
        system = str(kwargs["system"])
        if "candidate-better" in system and "strong role" in user:
            score, picks = 90, ["BB-001"]
        elif "candidate-better" in system and "weak role" in user:
            score, picks = 15, []
        elif "strong role" in user:
            score, picks = 60, ["BB-001"]
        elif "weak role" in user:
            score, picks = 55, ["BB-001"]
        else:
            score, picks = 50, []
        from jobhunt.fit.claude import AspectMatch

        matches = [
            AspectMatch(aspect_index=0, brag_doc_id=doc_id, similarity=0.9) for doc_id in picks
        ]
        return FitFields(score=score, matches=matches), _meta(STUDENT_MODEL, "0")

    return invoke
