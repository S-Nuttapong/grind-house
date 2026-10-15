"""Opus 5.5 writes fit rubrics. Haiku 5.5 is the only scorer. No model argument."""

import json
import re
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from jobhunt.fit.base import BragDoc, FitResult, FitUnavailable
from jobhunt.fit.claude import _RUBRIC, _V2_RUBRIC, _V3_RUBRIC, ClaudeFitScorer
from jobhunt.fit.eval import (
    BootstrapJob,
    FitReport,
    hit_at_k,
    icc,
    objective,
    paired_bootstrap,
    precision_at_k,
    quadratic_kappa,
    recall_at_k,
    retest_sd,
    reverse_order,
    score_quintile,
    spearman,
)

TEACHER_MODEL = "claude-opus-5-5"
STUDENT_MODEL = "claude-haiku-5-5"
DEV_JOBS = 60
LOOP_BUDGET_USD = Decimal("6")
LABEL_BUDGET_USD = Decimal("15")
OBJECTIVE_MARGIN = 0.02
WORST_JOBS = 20
MAX_RUBRIC_CHARS = 4000
_PROMPT_CHAR_CAP = 300_000

_STORY_ID = re.compile(r"BB-\d+")


class TeacherModelRejected(RuntimeError):
    """The teacher model id was rejected. Do not substitute another model."""


class _Ping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool


class RubricProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rubric: str
    rationale: str


_PROPOSAL_SYSTEM = """You rewrite the rubric a smaller model uses to score how well
brag stories cover a job.
Return a rubric and a one-sentence rationale.
The rubric must be general rules. Do not name a story id. Do not name a company.
Describe a stack by its technology, for example Spark or a data platform,
not by a vendor or company.
Keep the rubric under 4000 characters.
The scorer places your rubric after the stories. Each story is in a <doc id> tag.
Tell the scorer how to set score from 0 to 100 and similarity from 0 to 1,
and when to leave a match out.
"""

_REPAIR_SYSTEM = """You fix a rubric that used a banned word.
Return the rubric and a one-sentence rationale.
Change only the words named in the problems. Keep every other rule.
Describe a stack by its technology, for example Spark or a data platform,
not by a vendor or company.
Do not name a story id. Do not name a company.
"""

_REPAIRS = 2


@dataclass
class ScoredJob:
    job_id: int
    title: str
    company: str
    score: float | None
    scores: tuple[float, ...]
    order_delta: float | None
    picks: tuple[str, ...]
    similarities: tuple[float, ...]
    rating: float
    gold_docs: tuple[str, ...]
    aspects: tuple[str, ...]
    failed: bool
    cost_usd: float
    error: str | None = None


@dataclass
class VersionScore:
    name: str
    prompt_version: str
    rubric: str | None
    report: FitReport
    jobs: list[ScoredJob]
    failures: int
    cost_usd: Decimal

    @property
    def objective_value(self) -> float | None:
        return objective(self.report.precision_at_10, self.report.spearman)


def preflight_teacher() -> Any:
    """One tiny teacher call. Stop if the API rejects the model id."""
    from jobhunt.core import claude as claude_core

    try:
        _parsed, meta = claude_core.structured_call(
            model=TEACHER_MODEL,
            system="Reply with ok set to true.",
            user="ping",
            output=_Ping,
            max_tokens=64,
        )
    except claude_core.ClaudeError as exc:
        raise TeacherModelRejected(str(exc)) from exc
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        text = str(exc).lower()
        if status in {400, 404} or "not_found" in text:
            name = type(exc).__name__
            raise TeacherModelRejected(
                f"{TEACHER_MODEL} was rejected ({name}). Do not substitute another model."
            ) from exc
        raise
    return meta


def banned_words(companies: Sequence[str], story_ids: Sequence[str]) -> list[str]:
    """Words the teacher must not write. Short names are omitted, matching leak_reasons."""
    words = {story_id for story_id in story_ids if story_id}
    for company in companies:
        name = company.strip()
        if len(name) >= 3:
            words.add(name)
    return sorted(words, key=str.casefold)


def proposal_system(banned: Sequence[str]) -> str:
    """Teacher system prompt, including the words that would fail the leak guard."""
    return _PROPOSAL_SYSTEM + "Banned words: " + ", ".join(banned) + "\n"


def build_repair_user(rubric: str, reasons: Sequence[str], banned: Sequence[str]) -> str:
    """Ask the teacher to replace only the words the leak guard named."""
    problems = "\n".join(f"- {reason}" for reason in reasons)
    return (
        f"Problems:\n{problems}\n\nBanned words: {', '.join(banned)}\n\nRubric:\n{rubric.strip()}"
    )


def leak_reasons(rubric: str, companies: Sequence[str]) -> list[str]:
    """Reject a rubric that memorizes dev jobs instead of stating a general rule.

    Company names shorter than 3 characters are skipped. A name that short
    matches ordinary words and would reject every rubric.
    """
    reasons: list[str] = []
    if len(rubric) > MAX_RUBRIC_CHARS:
        reasons.append("rubric is over 4000 characters")
    if _STORY_ID.search(rubric):
        reasons.append("rubric contains a story id")
    folded = rubric.casefold()
    for company in companies:
        name = company.strip()
        if len(name) < 3:
            continue
        if name.casefold() in folded:
            reasons.append(f"rubric names {name}")
            break
    return reasons


def accept_candidate(
    candidate: float | None,
    best: float | None,
    gate_failures: Sequence[str],
    margin: float = OBJECTIVE_MARGIN,
) -> bool:
    """Keep a revision only when it clears the dev gates and the noise margin."""
    if gate_failures or candidate is None or best is None:
        return False
    return candidate >= best + margin


def dev_gate_failures(report: FitReport, failures: int) -> list[str]:
    reasons: list[str] = []
    if failures:
        reasons.append(f"{failures} FitUnavailable")
    if report.retest_sd is None or report.retest_sd > 5:
        reasons.append("retest sd above 5")
    if report.order_delta is None or report.order_delta > 5:
        reasons.append("order change above 5")
    return reasons


def rubric_text(prompt_version: str, rubric: str | None) -> str:
    if rubric is not None:
        return rubric
    if prompt_version == "v1":
        return _RUBRIC
    if prompt_version == "v3":
        return _V3_RUBRIC
    return _V2_RUBRIC


def build_proposal_user(
    *,
    best_rubric: str,
    best_metrics: dict[str, Any],
    history: Sequence[dict[str, Any]],
    worst: Sequence[ScoredJob],
    stories: Sequence[BragDoc],
) -> str:
    """Teacher prompt. Callers pass dev jobs only, so the test half stays out."""
    lines = [
        "Current best rubric:",
        best_rubric.strip(),
        "",
        "Current best dev metrics:",
        _metrics_line(best_metrics),
        "",
        "Earlier attempts:",
    ]
    if not history:
        lines.append("(none)")
    for attempt in history:
        lines.append(f"- kept={attempt['kept']} {_metrics_line(attempt)} rubric:")
        lines.append(str(attempt.get("rubric") or "").strip())
    lines.append("")
    lines.append("Worst dev jobs:")
    shown = _worst_that_fit(list(worst), stories, lines)
    for row in shown:
        lines.extend(_worst_job_lines(row))
    lines.append("")
    lines.append("Stories, first 200 characters:")
    for doc in stories:
        lines.append(f"{doc.id}: {doc.text[:200].replace(chr(10), ' ')}")
    return "\n".join(lines)


def score_version(
    docs: Sequence[BragDoc],
    jobs: Sequence[dict[str, Any]],
    gold_by_id: dict[int, Any],
    *,
    name: str,
    prompt_version: str,
    rubric: str | None,
    reps: int,
) -> VersionScore:
    """Score jobs with the student model. Does not write the database."""
    from jobhunt.composition import require_on_machine
    from jobhunt.core.claude import ClaudeError
    from jobhunt.fit import claude as claude_fit
    from jobhunt.fit.aspects import split_aspects

    if reps < 1:
        raise ValueError("reps must be at least 1")
    scorer = ClaudeFitScorer(STUDENT_MODEL, prompt_version=prompt_version, rubric=rubric)
    require_on_machine(scorer, "fit scorer")
    captured: list[tuple[int, Any]] = []
    local = threading.local()
    module: Any = claude_fit
    previous = module.structured_call

    def recording(**kwargs: Any) -> tuple[Any, Any]:
        try:
            parsed, meta = previous(**kwargs)
        except ClaudeError as exc:
            job_id = int(getattr(local, "job_id", 0))
            captured.extend((job_id, call) for call in exc.calls)
            raise
        captured.append((int(getattr(local, "job_id", 0)), meta))
        return parsed, meta

    module.structured_call = recording
    try:
        workers = max(1, min(scorer.concurrency, len(jobs)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            scored = list(
                pool.map(
                    lambda job: _score_job(
                        scorer, docs, job, gold_by_id, reps, local, split_aspects
                    ),
                    jobs,
                )
            )
    finally:
        module.structured_call = previous
    costs = _costs_by_job(captured)
    rows = [
        ScoredJob(
            job_id=row.job_id,
            title=row.title,
            company=row.company,
            score=row.score,
            scores=row.scores,
            order_delta=row.order_delta,
            picks=row.picks,
            similarities=row.similarities,
            rating=row.rating,
            gold_docs=row.gold_docs,
            aspects=row.aspects,
            failed=row.failed,
            cost_usd=float(costs.get(row.job_id, Decimal("0"))),
            error=row.error,
        )
        for row in scored
    ]
    spent = sum((costs.get(row.job_id, Decimal("0")) for row in rows), Decimal("0"))
    failures = sum(1 for row in rows if row.failed)
    return VersionScore(
        name=name,
        prompt_version=prompt_version,
        rubric=rubric,
        report=report_from_jobs(rows),
        jobs=rows,
        failures=failures,
        cost_usd=spent,
    )


def report_from_jobs(rows: Sequence[ScoredJob]) -> FitReport:
    ok = [row for row in rows if not row.failed and row.score is not None]
    if not ok:
        return FitReport(None, None, None, None, None, None)
    scores = [list(row.scores) for row in ok]
    first = [float(row.score) for row in ok if row.score is not None]
    ratings = [row.rating for row in ok]
    picks = [list(row.picks) for row in ok]
    expected = [list(row.gold_docs) for row in ok]
    deltas = [row.order_delta for row in ok if row.order_delta is not None]
    return FitReport(
        spearman=spearman(first, ratings),
        hit_at_10=hit_at_k(picks, expected, 10),
        kappa=quadratic_kappa(
            [score_quintile(score) for score in first], [int(rating) for rating in ratings]
        ),
        icc=icc(scores),
        retest_sd=retest_sd(scores),
        order_delta=(sum(deltas) / len(deltas)) if deltas else None,
        precision_at_10=precision_at_k(picks, expected, 10),
        recall_at_10=recall_at_k(picks, expected, 10),
    )


def optimize_prompt(
    sample: Path,
    gold: Path,
    dest: Path,
    rounds: int = 5,
    patience: int = 2,
    budget_usd: float = 6.0,
    *,
    reps: int = 2,
    dev_n: int = DEV_JOBS,
) -> dict[str, Any]:
    """Revise the student rubric on the dev half. The test half is never sent to the teacher."""
    from jobhunt.fit.roles import load_sample, split_fit_jobs

    budget = Decimal(str(budget_usd))
    payload = load_sample(sample)
    labels = load_gold_for_sample(gold, payload)
    dev_ids, _test_ids = split_fit_jobs(
        [int(job["job_id"]) for job in payload["jobs"]], seed=int(payload["seed"]), dev_n=dev_n
    )
    dev_jobs = [job for job in payload["jobs"] if int(job["job_id"]) in set(dev_ids)]
    docs = _docs(payload)
    companies = sorted({str(job["company"]) for job in dev_jobs})
    dest.mkdir(parents=True, exist_ok=True)
    saved = _saved_rounds(dest)
    state = _replay(saved)
    if 0 not in saved:
        if state.spent >= budget:
            _write_optimize_md(dest, saved, state)
            return {
                "stopped": "budget",
                "best": state.best_name,
                "spent_usd": format(state.spent, "f"),
                "scored_rounds": 0,
            }
        seed_rows = _score_seed(docs, dev_jobs, labels, reps)
        state = _apply_seed(state, seed_rows)
        saved[0] = _seed_payload(seed_rows, state)
        _write_round(dest, saved[0])
        print(f"round 0 best={state.best_name} spent_usd={state.spent}", flush=True)
    banned = banned_words(companies, [doc.id for doc in docs])
    number = max(saved, default=0) + 1
    while _scored_count(saved) < rounds and state.streak < patience and state.spent < budget:
        proposal = _propose_with_repairs(state, saved, docs, banned, companies, budget)
        rejected = leak_reasons(proposal.rubric, companies)
        if rejected:
            row = _rejected_payload(number, proposal, rejected, state)
            saved[number] = row
            _write_round(dest, row)
            state = _replay(saved)
            print(
                f"round {number} kept=no objective=None spent_usd={state.spent}",
                flush=True,
            )
            number += 1
            continue
        scored = score_version(
            docs,
            dev_jobs,
            labels,
            name=f"cand-r{number}",
            prompt_version=f"cand-r{number}",
            rubric=proposal.rubric,
            reps=reps,
        )
        gates = dev_gate_failures(scored.report, scored.failures)
        kept = accept_candidate(scored.objective_value, state.best_objective, gates)
        row = _proposal_payload(number, proposal, scored, kept, rejected, state)
        saved[number] = row
        _write_round(dest, row)
        state = _replay(saved)
        print(
            f"round {number} kept={kept} objective={scored.objective_value} "
            f"spent_usd={state.spent}",
            flush=True,
        )
        number += 1
    _write_optimize_md(dest, saved, state)
    return {
        "stopped": _stop_reason(state, rounds, patience, budget),
        "best": state.best_name,
        "best_objective": state.best_objective,
        "spent_usd": format(state.spent, "f"),
        "scored_rounds": _scored_count(saved),
    }


def decide_prompt(
    sample: Path,
    gold: Path,
    dest: Path,
    *,
    reps: int = 2,
    dev_n: int = DEV_JOBS,
    test_sample: Path | None = None,
    test_gold: Path | None = None,
) -> dict[str, Any]:
    """Score v1 and the best rubric once on the test half. Ship v2 only if it beats v1.

    With test_sample and test_gold, every job in that sample is the test set.
    With neither, the test half is split from sample. The dev half is never reused.
    """
    from jobhunt.fit.roles import load_sample, split_fit_jobs

    if (test_sample is None) != (test_gold is None):
        raise ValueError("test sample and test gold are both required")
    if test_sample is None or test_gold is None:
        payload = load_sample(sample)
        labels = load_gold_for_sample(gold, payload)
        _dev_ids, test_ids = split_fit_jobs(
            [int(job["job_id"]) for job in payload["jobs"]], seed=int(payload["seed"]), dev_n=dev_n
        )
        test_jobs = [job for job in payload["jobs"] if int(job["job_id"]) in set(test_ids)]
        gold_path = gold
    else:
        payload = load_sample(test_sample)
        labels = load_gold_for_sample(test_gold, payload)
        test_jobs = list(payload["jobs"])
        gold_path = test_gold
    docs = _docs(payload)
    saved = _saved_rounds(dest)
    if 0 not in saved:
        raise ValueError(f"no round 0 in {dest}")
    state = _replay(saved)
    v1 = _load_or_score(dest, "test-v1.json", docs, test_jobs, labels, "v1", "v1", None, reps)
    best_rubric = None if state.best_prompt_version == "v1" else state.best_rubric
    if state.best_prompt_version == "v2":
        best_rubric = None
    challenger = _load_or_score(
        dest,
        "test-best.json",
        docs,
        test_jobs,
        labels,
        state.best_name,
        state.best_prompt_version if state.best_prompt_version != "v2" else "v2",
        best_rubric if state.best_prompt_version not in {"v1", "v2"} else None,
        reps,
    )
    intervals = _intervals(v1, challenger)
    gates = _test_gates(v1, challenger, intervals)
    shipped = not gates and state.best_prompt_version != "v1"
    if shipped:
        install_v2(rubric_text(challenger.prompt_version, challenger.rubric))
    report = dest / "prompt-before-after.md"
    report.write_text(
        render_before_after(
            docs, v1, challenger, intervals, gates, shipped, _teacher_counts(gold_path, saved)
        ),
        encoding="utf-8",
    )
    return {"shipped": shipped, "gates": gates, "report": str(report)}


def install_v2(rubric: str, path: Path | None = None) -> None:
    """Copy a winning rubric into the live v3 slot and make v3 the default.

    v3 has no score field. A rubric that asks the model for a 0 to 100 score
    will not match the schema, so strip those lines before installing.
    """
    from jobhunt.fit import claude as claude_fit

    target = path or Path(claude_fit.__file__)
    text = target.read_text(encoding="utf-8")
    marker_start = "# v3-rubric:start\n"
    marker_end = "# v3-rubric:end\n"
    start = text.index(marker_start) + len(marker_start)
    end = text.index(marker_end)
    installed = _match_only_rubric(rubric)
    text = text[:start] + f"_V3_RUBRIC = {installed!r}\n" + text[end:]
    text = text.replace('_PROMPT_VERSION = "v1"', '_PROMPT_VERSION = "v3"', 1)
    text = text.replace('_PROMPT_VERSION = "v2"', '_PROMPT_VERSION = "v3"', 1)
    target.write_text(text, encoding="utf-8")


def _match_only_rubric(rubric: str) -> str:
    """Drop lines that ask for a holistic score. v3 returns matches only."""
    kept = [
        line
        for line in rubric.splitlines()
        if "score is 0 to 100" not in line.lower()
        and not line.lower().startswith("85 to 100")
        and not line.lower().startswith("60 to 84")
        and not line.lower().startswith("40 to 59")
        and not line.lower().startswith("under 40")
    ]
    return "\n".join(kept).strip() + "\n"


def load_gold_for_sample(gold: Path, payload: dict[str, Any]) -> dict[int, Any]:
    from jobhunt.fit.roles import load_fit_gold

    doc_ids = {doc.id for doc in _docs(payload)}
    job_ids = {int(job["job_id"]) for job in payload["jobs"]}
    labels = load_fit_gold(gold, doc_ids, job_ids)
    return {label.job_id: label for label in labels}


def render_before_after(
    docs: Sequence[BragDoc],
    v1: VersionScore,
    challenger: VersionScore,
    intervals: dict[str, Any],
    gates: Sequence[str],
    shipped: bool,
    counts: dict[str, int],
) -> str:
    import difflib

    before = _preview(docs, "v1", None)
    after_rubric = rubric_text(challenger.prompt_version, challenger.rubric)
    after = _preview(docs, "v2", after_rubric)
    diff = "\n".join(
        difflib.unified_diff(
            rubric_text("v1", None).splitlines(),
            after_rubric.splitlines(),
            fromfile="v1",
            tofile="v2",
            lineterm="",
        )
    )
    verdict = "Shipped as v2." if shipped else "Kept v1. " + ("; ".join(gates) or "no challenger")
    lines = [
        "# Prompt before and after",
        "",
        (
            f"Teacher: {TEACHER_MODEL}, {counts['labels']} label calls, "
            f"{counts['proposals']} proposal calls"
        ),
        f"Student: {STUDENT_MODEL}",
        f"Haiku scored {counts.get('scored', 0)} rewrites",
        "",
        f"Verdict: {verdict}",
        "",
        "## Before (v1)",
        "",
        "### System",
        "",
        "```",
        before,
        "```",
        "",
        "### User message",
        "",
        "```",
        "Aspects:",
        "0. <aspect>",
        "```",
        "",
        "## After",
        "",
        "### System",
        "",
        "```",
        after,
        "```",
        "",
        "### User message",
        "",
        "```",
        "Aspects:",
        "0. <aspect>",
        "```",
        "",
        "## Rubric diff",
        "",
        "```",
        diff or "(no rubric change)",
        "```",
        "",
        "## Test metrics",
        "",
        _metrics_table(v1, challenger, intervals),
        "",
        "## Examples",
        "",
        _examples(v1, challenger),
        "",
    ]
    return "\n".join(lines)


def render_optimize_md(saved: dict[int, dict[str, Any]], seed_rubric: str, best_rubric: str) -> str:
    import difflib

    lines = [
        "# Prompt optimization",
        "",
        "| Round | Name | Objective | Precision | Spearman | Cost | Kept |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for number in sorted(saved):
        row = saved[number]
        if row["kind"] == "seed":
            for version in row["versions"]:
                lines.append(_md_row(f"0 {version['name']}", version, version["cost_usd"], True))
        else:
            metrics = row.get("metrics") or {}
            lines.append(_md_row(str(number), metrics, row["cost_usd"], bool(row["kept"])))
    diff = "\n".join(
        difflib.unified_diff(
            seed_rubric.splitlines(),
            best_rubric.splitlines(),
            fromfile="v2-seed",
            tofile="best",
            lineterm="",
        )
    )
    lines.extend(
        ["", "## Best rubric against the v2 seed", "", "```", diff or "(no change)", "```", ""]
    )
    return "\n".join(lines)


@dataclass
class _State:
    best_name: str = "v1"
    best_prompt_version: str = "v1"
    best_rubric: str | None = None
    best_objective: float | None = None
    streak: int = 0
    spent: Decimal = Decimal("0")


def _score_job(
    scorer: ClaudeFitScorer,
    docs: Sequence[BragDoc],
    job: dict[str, Any],
    gold_by_id: dict[int, Any],
    reps: int,
    local: threading.local,
    split_aspects: Any,
) -> ScoredJob:
    job_id = int(job["job_id"])
    local.job_id = job_id
    label = gold_by_id[job_id]
    description = str(job["description"])
    aspects = tuple(str(aspect) for aspect in split_aspects(description))
    title = str(job["title"])
    company = str(job["company"])
    rating = float(label.rating)
    gold_docs = tuple(str(doc_id) for doc_id in label.docs)
    scores: list[float] = []
    picks: tuple[str, ...] = ()
    similarities: tuple[float, ...] = ()
    try:
        for index in range(reps):
            result = scorer.fit(docs, description)
            scores.append(result.score)
            if index == 0:
                picks, similarities = _picks(result)
        reversed_score = scorer.fit(docs, reverse_order(description)).score
    except FitUnavailable as exc:
        return ScoredJob(
            job_id=job_id,
            title=title,
            company=company,
            score=scores[0] if scores else None,
            scores=tuple(scores),
            order_delta=None,
            picks=picks,
            similarities=similarities,
            rating=rating,
            gold_docs=gold_docs,
            aspects=aspects,
            failed=True,
            cost_usd=0.0,
            error=str(exc),
        )
    return ScoredJob(
        job_id=job_id,
        title=title,
        company=company,
        score=scores[0],
        scores=tuple(scores),
        order_delta=abs(scores[0] - reversed_score),
        picks=picks,
        similarities=similarities,
        rating=rating,
        gold_docs=gold_docs,
        aspects=aspects,
        failed=False,
        cost_usd=0.0,
        error=None,
    )


def _picks(result: FitResult) -> tuple[tuple[str, ...], tuple[float, ...]]:
    return (
        tuple(match.brag_doc_id for match in result.top_docs),
        tuple(match.similarity for match in result.top_docs),
    )


def _costs_by_job(captured: Sequence[tuple[int, Any]]) -> dict[int, Decimal]:
    totals: dict[int, Decimal] = {}
    for job_id, meta in captured:
        totals[job_id] = totals.get(job_id, Decimal("0")) + meta.cost_usd
    return totals


def _docs(payload: dict[str, Any]) -> list[BragDoc]:
    return [
        BragDoc(id=str(doc["id"]), text=str(doc["text"]))
        for doc in payload["docs"]
        if str(doc["id"]).startswith("BB-")
    ]


def _score_seed(
    docs: Sequence[BragDoc],
    jobs: Sequence[dict[str, Any]],
    labels: dict[int, Any],
    reps: int,
) -> list[VersionScore]:
    return [
        score_version(docs, jobs, labels, name="v1", prompt_version="v1", rubric=None, reps=reps),
        score_version(
            docs, jobs, labels, name="v2-seed", prompt_version="v2", rubric=None, reps=reps
        ),
    ]


def _apply_seed(state: _State, rows: Sequence[VersionScore]) -> _State:
    v1, v2 = rows
    state.spent += v1.cost_usd + v2.cost_usd
    state.best_name = "v1"
    state.best_prompt_version = "v1"
    state.best_rubric = None
    state.best_objective = v1.objective_value
    if v2.objective_value is not None and (
        v1.objective_value is None or v2.objective_value > v1.objective_value
    ):
        state.best_name = "v2-seed"
        state.best_prompt_version = "v2"
        state.best_rubric = _V2_RUBRIC
        state.best_objective = v2.objective_value
    return state


def _propose(
    state: _State, saved: dict[int, dict[str, Any]], docs: Sequence[BragDoc], banned: Sequence[str]
) -> "_Proposal":
    from jobhunt.core import claude as claude_core

    best_jobs = _jobs_for(saved, state.best_name)
    worst = sorted(best_jobs, key=_job_error, reverse=True)[:WORST_JOBS]
    history = _history(saved)
    user = build_proposal_user(
        best_rubric=rubric_text(state.best_prompt_version, state.best_rubric),
        best_metrics=_state_metrics(state, best_jobs),
        history=history,
        worst=worst,
        stories=docs,
    )
    parsed, meta = claude_core.structured_call(
        model=TEACHER_MODEL,
        system=proposal_system(banned),
        user=user,
        output=RubricProposal,
        max_tokens=8000,
    )
    return _Proposal(parsed.rubric, parsed.rationale, _call_dict(meta))


def _repair(rubric: str, reasons: Sequence[str], banned: Sequence[str]) -> "_Proposal":
    from jobhunt.core import claude as claude_core

    parsed, meta = claude_core.structured_call(
        model=TEACHER_MODEL,
        system=_REPAIR_SYSTEM,
        user=build_repair_user(rubric, reasons, banned),
        output=RubricProposal,
        max_tokens=8000,
    )
    return _Proposal(parsed.rubric, parsed.rationale, _call_dict(meta))


def _propose_with_repairs(
    state: _State,
    saved: dict[int, dict[str, Any]],
    docs: Sequence[BragDoc],
    banned: Sequence[str],
    companies: Sequence[str],
    budget: Decimal,
) -> "_Proposal":
    """Propose once, then up to two repairs. Stop before a call that would pass the budget."""
    proposal = _propose(state, saved, docs, banned)
    for _ in range(_REPAIRS):
        rejected = leak_reasons(proposal.rubric, companies)
        if not rejected:
            return proposal
        if state.spent + Decimal(proposal.call["cost_usd"]) >= budget:
            return proposal
        fixed = _repair(proposal.rubric, rejected, banned)
        proposal = _Proposal(fixed.rubric, fixed.rationale, _add_call(proposal.call, fixed.call))
    return proposal


def _add_call(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    cost = Decimal(str(base["cost_usd"])) + Decimal(str(extra["cost_usd"]))
    return {
        "model": extra["model"],
        "input_tokens": int(base["input_tokens"]) + int(extra["input_tokens"]),
        "output_tokens": int(base["output_tokens"]) + int(extra["output_tokens"]),
        "cache_read_tokens": int(base["cache_read_tokens"]) + int(extra["cache_read_tokens"]),
        "cache_write_tokens": int(base["cache_write_tokens"]) + int(extra["cache_write_tokens"]),
        "cost_usd": format(cost, "f"),
    }


def _scored_count(saved: dict[int, dict[str, Any]]) -> int:
    return sum(1 for number, row in saved.items() if number > 0 and _was_scored(row))


def _was_scored(row: dict[str, Any]) -> bool:
    if "scored" in row:
        return bool(row["scored"])
    return row.get("metrics") is not None or bool(row.get("jobs"))


@dataclass
class _Proposal:
    rubric: str
    rationale: str
    call: dict[str, Any]


def _job_error(row: ScoredJob) -> float:
    if row.failed or row.score is None:
        return 1_000.0
    return abs(row.score - row.rating * 20)


def _worst_that_fit(
    worst: list[ScoredJob], stories: Sequence[BragDoc], prefix: list[str]
) -> list[ScoredJob]:
    shown = worst[:WORST_JOBS]
    while shown:
        draft = list(prefix)
        for row in shown:
            draft.extend(_worst_job_lines(row))
        for doc in stories:
            draft.append(doc.text[:200])
        if len("\n".join(draft)) <= _PROMPT_CHAR_CAP:
            return shown
        shown = shown[:-1]
    return []


def _worst_job_lines(row: ScoredJob) -> list[str]:
    picks = ", ".join(
        f"{doc_id} {similarity:.2f}"
        for doc_id, similarity in zip(row.picks, row.similarities, strict=False)
    )
    gold = ", ".join(row.gold_docs) or "(none)"
    lines = [
        (
            f"job {row.job_id} score={row.score} rating={row.rating} "
            f"picks={picks or '(none)'} gold={gold}"
        ),
        "aspects:",
    ]
    for index, aspect in enumerate(row.aspects[:40]):
        lines.append(f"{index}. {aspect[:200]}")
    return lines


def _metrics_line(metrics: dict[str, Any]) -> str:
    return (
        f"objective={metrics.get('objective')} precision={metrics.get('precision_at_10')} "
        f"spearman={metrics.get('spearman')} retest_sd={metrics.get('retest_sd')} "
        f"order_delta={metrics.get('order_delta')} failures={metrics.get('failures')}"
    )


def _history(saved: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if 0 in saved:
        for version in saved[0]["versions"]:
            rows.append(
                {
                    "kept": version["name"] == saved[0]["best_name"],
                    "rubric": rubric_text(version["prompt_version"], version.get("rubric")),
                    **_public_metrics(version),
                }
            )
    for number in sorted(number for number in saved if number > 0):
        row = saved[number]
        metrics = row.get("metrics") or {}
        rows.append(
            {
                "kept": bool(row["kept"]),
                "rubric": row.get("rubric"),
                "rejected": row.get("rejected"),
                **metrics,
            }
        )
    return rows


def _state_metrics(state: _State, jobs: Sequence[ScoredJob]) -> dict[str, Any]:
    report = report_from_jobs(list(jobs))
    return {
        "objective": state.best_objective,
        "precision_at_10": report.precision_at_10,
        "spearman": report.spearman,
        "retest_sd": report.retest_sd,
        "order_delta": report.order_delta,
        "failures": sum(1 for job in jobs if job.failed),
    }


def _jobs_for(saved: dict[int, dict[str, Any]], name: str) -> list[ScoredJob]:
    for number in sorted(saved, reverse=True):
        row = saved[number]
        if row["kind"] == "seed":
            for version in row["versions"]:
                if version["name"] == name:
                    return [_job_load(item) for item in version["jobs"]]
        elif row.get("name") == name and row.get("jobs"):
            return [_job_load(item) for item in row["jobs"]]
    return []


def _saved_rounds(dest: Path) -> dict[int, dict[str, Any]]:
    found: dict[int, dict[str, Any]] = {}
    if not dest.exists():
        return found
    for path in dest.glob("round-*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        found[int(payload["round"])] = payload
    return _contiguous(found)


def _contiguous(found: dict[int, dict[str, Any]]) -> dict[int, dict[str, Any]]:
    kept: dict[int, dict[str, Any]] = {}
    number = 0
    while number in found:
        kept[number] = found[number]
        number += 1
    return kept


def _replay(saved: dict[int, dict[str, Any]]) -> _State:
    state = _State()
    if not saved:
        return state
    for number in sorted(saved):
        row = saved[number]
        state.spent += Decimal(str(row["cost_usd"]))
        state.best_name = str(row["best_name"])
        state.best_prompt_version = str(row["best_prompt_version"])
        state.best_rubric = row.get("best_rubric")
        state.best_objective = row.get("best_objective")
        state.streak = int(row["streak"])
    return state


def _seed_payload(rows: Sequence[VersionScore], state: _State) -> dict[str, Any]:
    return {
        "round": 0,
        "kind": "seed",
        "versions": [_version_dump(row) for row in rows],
        "best_name": state.best_name,
        "best_prompt_version": state.best_prompt_version,
        "best_rubric": state.best_rubric,
        "best_objective": state.best_objective,
        "streak": 0,
        "kept": True,
        "cost_usd": format(sum((row.cost_usd for row in rows), Decimal("0")), "f"),
    }


def _rejected_payload(
    number: int, proposal: _Proposal, rejected: Sequence[str], state: _State
) -> dict[str, Any]:
    cost = Decimal(str(proposal.call["cost_usd"]))
    return {
        "round": number,
        "kind": "proposal",
        "name": f"cand-r{number}",
        "rubric": proposal.rubric,
        "rationale": proposal.rationale,
        "proposal_call": proposal.call,
        "rejected": list(rejected),
        "kept": False,
        "metrics": None,
        "jobs": [],
        "best_name": state.best_name,
        "best_prompt_version": state.best_prompt_version,
        "best_rubric": state.best_rubric,
        "best_objective": state.best_objective,
        "streak": state.streak,
        "scored": False,
        "cost_usd": format(cost, "f"),
    }


def _proposal_payload(
    number: int,
    proposal: _Proposal,
    scored: VersionScore,
    kept: bool,
    rejected: Sequence[str],
    state: _State,
) -> dict[str, Any]:
    cost = Decimal(str(proposal.call["cost_usd"])) + scored.cost_usd
    best_name = scored.name if kept else state.best_name
    best_version = scored.prompt_version if kept else state.best_prompt_version
    best_rubric = scored.rubric if kept else state.best_rubric
    best_objective = scored.objective_value if kept else state.best_objective
    return {
        "round": number,
        "kind": "proposal",
        "name": scored.name,
        "rubric": proposal.rubric,
        "rationale": proposal.rationale,
        "proposal_call": proposal.call,
        "rejected": list(rejected),
        "kept": kept,
        "metrics": _public_metrics(_version_dump(scored)),
        "jobs": [_job_dump(job) for job in scored.jobs],
        "best_name": best_name,
        "best_prompt_version": best_version,
        "best_rubric": best_rubric,
        "best_objective": best_objective,
        "streak": 0 if kept else state.streak + 1,
        "scored": True,
        "cost_usd": format(cost, "f"),
    }


def _version_dump(row: VersionScore) -> dict[str, Any]:
    report = row.report
    return {
        "name": row.name,
        "prompt_version": row.prompt_version,
        "rubric": row.rubric,
        "objective": row.objective_value,
        "precision_at_10": report.precision_at_10,
        "recall_at_10": report.recall_at_10,
        "spearman": report.spearman,
        "retest_sd": report.retest_sd,
        "order_delta": report.order_delta,
        "failures": row.failures,
        "cost_usd": format(row.cost_usd, "f"),
        "jobs": [_job_dump(job) for job in row.jobs],
    }


def _public_metrics(version: dict[str, Any]) -> dict[str, Any]:
    return {
        "objective": version.get("objective"),
        "precision_at_10": version.get("precision_at_10"),
        "spearman": version.get("spearman"),
        "retest_sd": version.get("retest_sd"),
        "order_delta": version.get("order_delta"),
        "failures": version.get("failures"),
    }


def _job_dump(row: ScoredJob) -> dict[str, Any]:
    return {
        "job_id": row.job_id,
        "title": row.title,
        "company": row.company,
        "score": row.score,
        "scores": list(row.scores),
        "order_delta": row.order_delta,
        "picks": list(row.picks),
        "similarities": list(row.similarities),
        "rating": row.rating,
        "gold_docs": list(row.gold_docs),
        "aspects": list(row.aspects),
        "failed": row.failed,
        "cost_usd": row.cost_usd,
        "error": row.error,
    }


def _job_load(payload: dict[str, Any]) -> ScoredJob:
    return ScoredJob(
        job_id=int(payload["job_id"]),
        title=str(payload["title"]),
        company=str(payload["company"]),
        score=None if payload["score"] is None else float(payload["score"]),
        scores=tuple(float(score) for score in payload["scores"]),
        order_delta=None if payload["order_delta"] is None else float(payload["order_delta"]),
        picks=tuple(payload["picks"]),
        similarities=tuple(float(value) for value in payload["similarities"]),
        rating=float(payload["rating"]),
        gold_docs=tuple(payload["gold_docs"]),
        aspects=tuple(payload["aspects"]),
        failed=bool(payload["failed"]),
        cost_usd=float(payload["cost_usd"]),
        error=payload.get("error"),
    )


def _call_dict(meta: Any) -> dict[str, Any]:
    return {
        "model": meta.model,
        "input_tokens": meta.input_tokens,
        "output_tokens": meta.output_tokens,
        "cache_read_tokens": meta.cache_read_tokens,
        "cache_write_tokens": meta.cache_write_tokens,
        "cost_usd": format(meta.cost_usd, "f"),
    }


def _write_round(dest: Path, payload: dict[str, Any]) -> None:
    path = dest / f"round-{payload['round']}.json"
    _write_json(path, payload)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_optimize_md(dest: Path, saved: dict[int, dict[str, Any]], state: _State) -> None:
    text = render_optimize_md(
        saved,
        _V2_RUBRIC,
        rubric_text(state.best_prompt_version, state.best_rubric),
    )
    (dest / "optimize.md").write_text(text, encoding="utf-8")


def _stop_reason(state: _State, rounds: int, patience: int, budget: Decimal) -> str:
    if state.spent >= budget:
        return "budget"
    if state.streak >= patience:
        return "patience"
    return "rounds"


def _md_row(name: str, metrics: dict[str, Any], cost: str, kept: bool) -> str:
    return (
        f"| {name} | {metrics.get('name', name)} | {metrics.get('objective')} "
        f"| {metrics.get('precision_at_10')} | {metrics.get('spearman')} | {cost} | {kept} |"
    )


def _load_or_score(
    dest: Path,
    filename: str,
    docs: Sequence[BragDoc],
    jobs: Sequence[dict[str, Any]],
    labels: dict[int, Any],
    name: str,
    prompt_version: str,
    rubric: str | None,
    reps: int,
) -> VersionScore:
    path = dest / filename
    if path.is_file():
        return _version_load(json.loads(path.read_text(encoding="utf-8")))
    scored = score_version(
        docs,
        jobs,
        labels,
        name=name,
        prompt_version=prompt_version,
        rubric=rubric,
        reps=reps,
    )
    _write_json(path, _version_dump(scored))
    return scored


def _version_load(payload: dict[str, Any]) -> VersionScore:
    jobs = [_job_load(item) for item in payload["jobs"]]
    return VersionScore(
        name=str(payload["name"]),
        prompt_version=str(payload["prompt_version"]),
        rubric=payload.get("rubric"),
        report=report_from_jobs(jobs),
        jobs=jobs,
        failures=int(payload["failures"]),
        cost_usd=Decimal(str(payload["cost_usd"])),
    )


def _intervals(v1: VersionScore, challenger: VersionScore) -> dict[str, Any]:
    usable = [job for job in v1.jobs if not job.failed and job.score is not None]
    right_by_id = {
        job.job_id: job for job in challenger.jobs if not job.failed and job.score is not None
    }
    paired_left: list[BootstrapJob] = []
    paired_right: list[BootstrapJob] = []
    for job in usable:
        other = right_by_id.get(job.job_id)
        if other is None:
            continue
        paired_left.append(_bootstrap_job(job))
        paired_right.append(_bootstrap_job(other))
    if not paired_left:
        return {}
    return paired_bootstrap(paired_left, paired_right, seed=20261012)


def _bootstrap_job(row: ScoredJob) -> BootstrapJob:
    return BootstrapJob(
        score=float(row.score or 0),
        rating=row.rating,
        picks=row.picks,
        gold_docs=row.gold_docs,
        scores=row.scores,
        order_delta=row.order_delta,
        cost_usd=row.cost_usd,
    )


def _test_gates(v1: VersionScore, challenger: VersionScore, intervals: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    band = intervals.get("objective")
    low = None if band is None else band.low
    if low is None or low <= 0:
        reasons.append(f"objective 95% lower bound {low} is not above 0")
    point = _point(challenger.report.spearman, v1.report.spearman)
    if point is None or point < 0:
        reasons.append(f"spearman delta {point} is negative")
    reasons.extend(dev_gate_failures(challenger.report, challenger.failures))
    v1_cost = _per_job(v1)
    v2_cost = _per_job(challenger)
    if v1_cost > 0 and v2_cost > v1_cost * Decimal("1.5"):
        reasons.append(f"cost per job {v2_cost} is above 1.5x {v1_cost}")
    if challenger.prompt_version == "v1":
        reasons.append("best rubric is still v1")
    return reasons


def _point(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _per_job(row: VersionScore) -> Decimal:
    count = len(row.jobs) or 1
    return row.cost_usd / Decimal(count)


def _teacher_counts(gold: Path, saved: dict[int, dict[str, Any]]) -> dict[str, int]:
    import yaml

    payload = yaml.safe_load(gold.read_text(encoding="utf-8"))
    labels = len(payload.get("jobs", [])) if isinstance(payload, dict) else 0
    proposals = sum(
        1 for row in saved.values() if row.get("kind") == "proposal" and row.get("proposal_call")
    )
    scored = sum(1 for row in saved.values() if row.get("kind") == "proposal" and row.get("scored"))
    return {"labels": labels, "proposals": proposals, "scored": scored}


def _preview(docs: Sequence[BragDoc], version: str, rubric: str | None) -> str:
    from jobhunt.fit.claude import system_prompt

    short = [BragDoc(id=doc.id, text=doc.text.split("\n", 1)[0]) for doc in docs]
    return system_prompt(short, version=version, rubric=rubric)


def _metrics_table(v1: VersionScore, challenger: VersionScore, intervals: dict[str, Any]) -> str:
    rows = [
        (
            "precision at 10",
            v1.report.precision_at_10,
            challenger.report.precision_at_10,
            "precision",
        ),
        ("recall at 10", v1.report.recall_at_10, challenger.report.recall_at_10, "recall"),
        ("spearman", v1.report.spearman, challenger.report.spearman, "spearman"),
        ("objective", v1.objective_value, challenger.objective_value, "objective"),
        ("lineup size", _mean_lineup(v1), _mean_lineup(challenger), "lineup"),
        ("retest_sd", v1.report.retest_sd, challenger.report.retest_sd, "retest_sd"),
        ("order_delta", v1.report.order_delta, challenger.report.order_delta, "order_delta"),
        ("cost per job", float(_per_job(v1)), float(_per_job(challenger)), "cost"),
    ]
    lines = ["| Metric | v1 | v2 | Delta | 95% interval |", "| --- | --- | --- | --- | --- |"]
    for label, first, second, key in rows:
        delta = None if first is None or second is None else second - first
        band = intervals.get(key)
        span = "n/a" if band is None else f"{band.low:.3f} to {band.high:.3f}"
        lines.append(f"| {label} | {_num(first)} | {_num(second)} | {_num(delta)} | {span} |")
    return "\n".join(lines)


def _mean_lineup(row: VersionScore) -> float | None:
    ok = [job for job in row.jobs if not job.failed]
    if not ok:
        return None
    return sum(len(job.picks) for job in ok) / len(ok)


def _num(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"


def _examples(v1: VersionScore, challenger: VersionScore) -> str:
    right = {job.job_id: job for job in challenger.jobs}
    gains = []
    for job in v1.jobs:
        other = right.get(job.job_id)
        if other is None:
            continue
        gains.append((_job_term(other) - _job_term(job), job, other))
    gains.sort(key=lambda item: item[0], reverse=True)
    picked: list[tuple[float, ScoredJob, ScoredJob]] = []
    seen: set[int] = set()
    for item in gains[:3] + list(reversed(gains)):
        if item[1].job_id in seen:
            continue
        picked.append(item)
        seen.add(item[1].job_id)
        if len(picked) == 5:
            break
    lines: list[str] = []
    for delta, left, other in picked:
        gold = ", ".join(left.gold_docs) or "(none)"
        lines.append(f"### {left.title} ({left.company}), gain {delta:.3f}")
        lines.append(f"Opus: {gold}")
        lines.append(f"v1: {_lineup(left)}")
        lines.append(f"v2: {_lineup(other)}")
        lines.append("")
    return "\n".join(lines)


def _job_term(row: ScoredJob) -> float:
    if not row.picks:
        precision = 1.0 if not row.gold_docs else 0.0
    else:
        wanted = set(row.gold_docs)
        precision = sum(1 for doc in row.picks if doc in wanted) / len(row.picks)
    error = 0.0 if row.score is None else min(1.0, abs(row.score - row.rating * 20) / 100)
    return 0.5 * precision + 0.5 * (1 - error)


def _lineup(row: ScoredJob) -> str:
    wanted = set(row.gold_docs)
    parts = []
    for doc_id, similarity in zip(row.picks, row.similarities, strict=False):
        mark = "match" if doc_id in wanted else "miss"
        parts.append(f"{doc_id} {similarity:.2f} {mark}")
    return ", ".join(parts) or "(none)"
