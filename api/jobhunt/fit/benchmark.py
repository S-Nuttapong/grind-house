"""Compare stored default scores with the existing Claude scorer on one frozen sample.

Sampling and statistics are deterministic. Scoring calls ClaudeFitScorer; this module
does not write job_fits. Judges see only the blinded packet.
"""

import hashlib
import json
import random
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jobhunt.fit.base import BragDoc, FitResult, FitUnavailable
from jobhunt.fit.calibrate import tier
from jobhunt.fit.eval import hit_at_k, spearman

TIERS = ("low", "fair", "good", "strong")
LOW_CONFIDENCE = 0.6
SAMPLE_SIZE = 60
_TIER_INDEX = {name: index for index, name in enumerate(TIERS)}

RAW_JSON = "raw.json"
RAW_MARKDOWN = "raw.md"
RAW_DIGEST = "raw.sha256"
IDENTITY_JSON = "identity.json"
BLIND_JSON = "blinded/packet.json"
RUBRIC_MARKDOWN = "blinded/rubric.md"
OPUS_JSON = "reviews/opus.json"
SOL_JSON = "reviews/sol.json"

_FITS_SQL = """
SELECT j.id, j.title, j.description_md, f.score, f.raw, f.coverage, f.gaps
FROM job_fits f
JOIN jobs j ON j.id = f.job_id
WHERE j.closed_at IS NULL
  AND f.model_id = %s
  AND f.source_hash = %s
ORDER BY j.id
"""

_MATCHES_SQL = """
SELECT job_id, doc_ref, aspect, similarity
FROM job_fit_matches
WHERE model_id = %s AND source_hash = %s
ORDER BY job_id, rank
"""


class BenchmarkError(Exception):
    """The sample, the frozen result, or a judge review cannot be used."""


class JobJudgment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: int
    preference: str = Field(pattern="^(A|B|tie)$")
    confidence: float = Field(ge=0, le=1)
    rating: int = Field(ge=1, le=5)
    evidence: str
    expected_docs: list[str] = Field(default_factory=list)


class JudgeReview(BaseModel):
    """A blinded review. Preferences name packet letters, not models."""

    model_config = ConfigDict(extra="forbid")

    recommendation: str = Field(pattern="^(A|B|tie|inconclusive)$")
    summary: str
    themes: list[str]
    limitations: list[str]
    jobs: list[JobJudgment]


@dataclass(frozen=True)
class PopulationJob:
    job_id: int
    title: str
    scored_text: str
    score: float
    raw: float
    coverage: float
    gaps: tuple[str, ...]
    matches: tuple[tuple[str, str, float], ...]

    @property
    def tier(self) -> str:
        return tier(self.score)


@dataclass(frozen=True)
class CandidateOutcome:
    job_id: int
    result: FitResult | None
    error: str | None
    latency_ms: float
    cost_usd: Decimal
    input_tokens: int
    output_tokens: int
    # Every match the model returned, so the evidence score can be recomputed
    # without another call. (aspect_index, doc_id, similarity).
    matches: tuple[tuple[int, str, float], ...] = ()


@dataclass(frozen=True)
class QueueCase:
    job_id: int
    opus_preference: str | None
    sol_preference: str | None
    opus_confidence: float | None
    sol_confidence: float | None
    baseline_tier: str
    candidate_tier: str | None
    score_delta: float | None


class CandidateScorer(Protocol):
    def fit(self, docs: Sequence[BragDoc], job_description: str) -> FitResult: ...


InvokeModel = Callable[..., tuple[Any, Any]]


def stratified_sample(jobs: Sequence[PopulationJob], *, n: int, seed: int) -> list[PopulationJob]:
    """Take an even share from each tier, then fill shortages from leftover rows.

    Each tier is shuffled with its own seed so one tier's size does not change
    another's draw. Leftover quota is filled in tier order.
    """
    if n < 0:
        raise BenchmarkError("sample size cannot be negative")
    grouped = {name: [job for job in jobs if job.tier == name] for name in TIERS}
    unknown = [job.job_id for job in jobs if job.tier not in grouped]
    if unknown:
        raise BenchmarkError(f"jobs have no tier: {unknown}")
    pools = {name: _shuffled(grouped[name], f"{seed}:{name}") for name in TIERS}
    base, remainder = divmod(n, len(TIERS))
    quotas = {name: base + (1 if index < remainder else 0) for index, name in enumerate(TIERS)}
    chosen: list[PopulationJob] = []
    shortfall = 0
    for name in TIERS:
        take = min(len(pools[name]), quotas[name])
        chosen.extend(pools[name][:take])
        pools[name] = pools[name][take:]
        shortfall += quotas[name] - take
    for name in TIERS:
        if shortfall <= 0:
            break
        extra = pools[name][:shortfall]
        chosen.extend(extra)
        shortfall -= len(extra)
    return sorted(chosen, key=lambda job: job.job_id)


def blind_letters(job_id: int, seed: int) -> dict[str, str]:
    """Assign the two systems to A and B. The same seed and job always agree."""
    digest = hashlib.sha256(f"{seed}\n{job_id}".encode()).digest()
    first = "baseline" if digest[0] < 128 else "candidate"
    second = "candidate" if first == "baseline" else "baseline"
    return {"A": first, "B": second}


def wilson_interval(successes: int, trials: int, *, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval for a proportion. None when there are no trials."""
    if trials <= 0:
        return None
    if successes < 0 or successes > trials:
        raise BenchmarkError("successes must be between 0 and the number of trials")
    proportion = successes / trials
    z_squared = z * z
    denominator = 1 + z_squared / trials
    center = (proportion + z_squared / (2 * trials)) / denominator
    spread = z * (proportion * (1 - proportion) / trials + z_squared / (4 * trials * trials)) ** 0.5
    margin = spread / denominator
    return (max(0.0, center - margin), min(1.0, center + margin))


def review_queue(cases: Sequence[QueueCase], *, limit: int, seed: int) -> list[int]:
    """Disagreements, low confidence, large tier moves, then a seeded audit."""
    if limit < 0:
        raise BenchmarkError("review limit cannot be negative")
    chosen: list[QueueCase] = []
    chosen.extend(_ordered_for_review(case for case in cases if _needs_decision(case)))
    chosen.extend(_ordered_for_review(case for case in cases if _is_low_confidence(case)))
    chosen_ids = {case.job_id for case in chosen}
    rest = [case for case in cases if case.job_id not in chosen_ids]
    changes = [case for case in rest if _tier_distance(case) > 0]
    chosen.extend(_ordered_for_review(changes))
    chosen_ids = {case.job_id for case in chosen}
    audit = [case for case in rest if case.job_id not in chosen_ids and _is_agreement(case)]
    audit = sorted(audit, key=lambda case: case.job_id)
    random.Random(seed).shuffle(audit)
    chosen.extend(audit)
    return [case.job_id for case in chosen[:limit]]


def parse_judge_review(payload: object) -> JudgeReview:
    if not isinstance(payload, dict):
        raise BenchmarkError("judge review must be a JSON object")
    try:
        review = JudgeReview.model_validate(payload)
    except ValidationError as exc:
        raise BenchmarkError("judge review does not match the schema") from exc
    seen: set[int] = set()
    for job in review.jobs:
        if job.job_id in seen:
            raise BenchmarkError(f"duplicate judgment for job {job.job_id}")
        seen.add(job.job_id)
    return review


def judge_metrics(
    jobs: Sequence[Mapping[str, Any]],
    identity: Mapping[str, Any],
    review: JudgeReview,
) -> dict[str, Any]:
    """Win rate and secondary scores for one judge. Ties are not decisive."""
    by_id = {int(job["job_id"]): job for job in jobs}
    letters = identity["jobs"]
    candidate_wins = 0
    ties = 0
    ratings: list[float] = []
    baseline_scores: list[float] = []
    candidate_scores: list[float] = []
    baseline_docs: list[list[str]] = []
    candidate_docs: list[list[str]] = []
    expected_docs: list[list[str]] = []
    for item in review.jobs:
        job = by_id.get(item.job_id)
        if job is None:
            raise BenchmarkError(f"judgment for unknown job {item.job_id}")
        mapping = letters.get(str(item.job_id))
        if not isinstance(mapping, dict):
            raise BenchmarkError(f"missing blind letters for job {item.job_id}")
        if item.preference == "tie":
            ties += 1
        elif mapping.get(item.preference) == "candidate":
            candidate_wins += 1
        elif mapping.get(item.preference) != "baseline":
            raise BenchmarkError(f"blind letters for job {item.job_id} are incomplete")
        _collect_secondary(
            job,
            item,
            ratings,
            baseline_scores,
            candidate_scores,
            baseline_docs,
            candidate_docs,
            expected_docs,
        )
    judged = len(review.jobs)
    decisive = judged - ties
    interval = wilson_interval(candidate_wins, decisive)
    return {
        "recommendation": review.recommendation,
        "summary": review.summary,
        "themes": list(review.themes),
        "limitations": list(review.limitations),
        "judged": judged,
        "missing": len(by_id) - judged,
        "ties": ties,
        "decisive": decisive,
        "candidate_wins": candidate_wins,
        "candidate_win_rate": None if decisive == 0 else candidate_wins / decisive,
        "tie_rate": None if judged == 0 else ties / judged,
        "wilson95": None if interval is None else [interval[0], interval[1]],
        "spearman_baseline": spearman(baseline_scores, ratings),
        "spearman_candidate": spearman(candidate_scores, ratings),
        "hit_at_10_baseline": hit_at_k(baseline_docs, expected_docs, 10),
        "hit_at_10_candidate": hit_at_k(candidate_docs, expected_docs, 10),
    }


def queue_cases(
    jobs: Sequence[Mapping[str, Any]],
    identity: Mapping[str, Any],
    opus: JudgeReview | None,
    sol: JudgeReview | None,
) -> list[QueueCase]:
    opus_by_id = {} if opus is None else {item.job_id: item for item in opus.jobs}
    sol_by_id = {} if sol is None else {item.job_id: item for item in sol.jobs}
    cases: list[QueueCase] = []
    for job in jobs:
        job_id = int(job["job_id"])
        left = opus_by_id.get(job_id)
        right = sol_by_id.get(job_id)
        candidate = job.get("candidate")
        baseline_score = float(job["baseline"]["score"])
        candidate_score = None if candidate is None else float(candidate["score"])
        cases.append(
            QueueCase(
                job_id=job_id,
                opus_preference=None if left is None else left.preference,
                sol_preference=None if right is None else right.preference,
                opus_confidence=None if left is None else left.confidence,
                sol_confidence=None if right is None else right.confidence,
                baseline_tier=str(job["baseline"]["tier"]),
                candidate_tier=None if candidate is None else str(candidate["tier"]),
                score_delta=None if candidate_score is None else candidate_score - baseline_score,
            )
        )
    return cases


def build_payload(
    *,
    seed: int,
    mode: str,
    source_hash: str,
    baseline_model_id: str,
    candidate_model_id: str,
    docs: Sequence[BragDoc],
    selected: Sequence[PopulationJob],
    outcomes: Sequence[CandidateOutcome],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return the named raw result, the separate identity key, and the blinded packet."""
    by_outcome = {outcome.job_id: outcome for outcome in outcomes}
    if set(by_outcome) != {job.job_id for job in selected}:
        raise BenchmarkError("candidate outcomes do not match the sample")
    doc_text = {doc.id: doc.text for doc in docs}
    records = [_job_record(job, by_outcome[job.job_id], doc_text) for job in selected]
    raw = {
        "seed": seed,
        "mode": mode,
        "source_hash": source_hash,
        "baseline_model_id": baseline_model_id,
        "candidate_model_id": candidate_model_id,
        "docs": [{"id": doc.id, "text": doc.text} for doc in docs],
        "jobs": records,
        "summary": pair_summary(records),
    }
    identity = {
        "seed": seed,
        "baseline_model_id": baseline_model_id,
        "candidate_model_id": candidate_model_id,
        "jobs": {str(job.job_id): blind_letters(job.job_id, seed) for job in selected},
    }
    return raw, identity, blinded_packet(raw, identity)


def pair_summary(jobs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    deltas: list[float] = []
    latencies: list[float] = []
    cost = Decimal("0")
    failures = 0
    tier_changes = 0
    confusion = {left: {right: 0 for right in TIERS} for left in TIERS}
    for job in jobs:
        latencies.append(float(job["latency_ms"]))
        cost += Decimal(str(job["cost_usd"]))
        candidate = job.get("candidate")
        if candidate is None:
            failures += 1
            continue
        deltas.append(float(candidate["score"]) - float(job["baseline"]["score"]))
        left = str(job["baseline"]["tier"])
        right = str(candidate["tier"])
        confusion[left][right] += 1
        if left != right:
            tier_changes += 1
    return {
        "jobs": len(jobs),
        "failures": failures,
        "failure_rate": None if not jobs else failures / len(jobs),
        "cost_usd": format(cost, "f"),
        "median_latency_ms": _median(latencies),
        "median_score_delta": _median(deltas),
        "tier_changes": tier_changes,
        "tier_confusion": confusion,
    }


def blinded_packet(raw: Mapping[str, Any], identity: Mapping[str, Any]) -> dict[str, Any]:
    letters = identity["jobs"]
    jobs: list[dict[str, Any]] = []
    for job in raw["jobs"]:
        mapping = letters[str(job["job_id"])]
        sides = {"baseline": _public_side(job["baseline"]), "candidate": _public_candidate(job)}
        jobs.append(
            {
                "job_id": job["job_id"],
                "title": job["title"],
                "scored_text": job["scored_text"],
                "aspects": job["aspects"],
                "A": sides[mapping["A"]],
                "B": sides[mapping["B"]],
            }
        )
    return {"docs": raw["docs"], "jobs": jobs}


def render_raw_markdown(raw: Mapping[str, Any]) -> str:
    summary = raw["summary"]
    delta = summary["median_score_delta"]
    latency = summary["median_latency_ms"]
    lines = [
        "# Fit benchmark raw result",
        "",
        f"- Sample: {summary['jobs']} jobs",
        f"- Seed: {raw['seed']}",
        f"- Mode: {raw['mode']}",
        f"- Source hash: {raw['source_hash']}",
        f"- Baseline: {raw['baseline_model_id']}",
        f"- Candidate: {raw['candidate_model_id']}",
        f"- Failures: {summary['failures']}/{summary['jobs']}",
        f"- Candidate cost (USD): {summary['cost_usd']}",
        f"- Median latency (ms): {_plain(latency)}",
        f"- Median score delta (candidate minus baseline): {_plain(delta)}",
        f"- Tier changes: {summary['tier_changes']}",
        "",
        "Tier confusion, baseline rows by candidate columns (low, fair, good, strong):",
        "",
    ]
    header = "| baseline | " + " | ".join(TIERS) + " |"
    rule = "| --- | " + " | ".join("---" for _tier in TIERS) + " |"
    lines.extend([header, rule])
    for left in TIERS:
        cells = [str(summary["tier_confusion"][left][right]) for right in TIERS]
        lines.append(f"| {left} | " + " | ".join(cells) + " |")
    lines.extend(["", "This file has no judge conclusions.", ""])
    return "\n".join(lines)


def rubric_markdown() -> str:
    return """# Blinded fit review

Compare output A with output B for each job. You do not know which system
produced either output. Use the job text, the aspects, and the brag docs.
Doc ids in an output must come from the doc list.

For every job, decide which output is the better resume-evidence selection:

- Prefer the output whose cited docs actually cover the aspects.
- A higher score is not better when the cited docs do not support it.
- Choose tie when the outputs are equally useful.
- Set confidence from 0 to 1. Use below 0.6 when the text is too thin to decide.
- Rate overall fit from 1 to 5, independently of which output you prefer.
- expected_docs lists brag doc ids you would put on the resume.
  Use an empty list when you would not name any.

Write the JSON object you were asked to save, with this shape:

{
  "recommendation": "A",
  "summary": "one paragraph",
  "themes": ["what the outputs disagree about"],
  "limitations": ["what this packet cannot show"],
  "jobs": [
    {
      "job_id": 1,
      "preference": "A",
      "confidence": 0.8,
      "rating": 4,
      "evidence": "which cited docs cover or miss the aspects",
      "expected_docs": ["doc-id"]
    }
  ]
}

recommendation is A, B, tie, or inconclusive.
preference is A, B, or tie.
Do not rename the outputs or infer model names.
"""


def run_candidate(
    scorer: CandidateScorer,
    docs: Sequence[BragDoc],
    jobs: Sequence[PopulationJob],
    *,
    invoke_model: InvokeModel | None = None,
    progress: bool = False,
) -> list[CandidateOutcome]:
    """Score one job at a time so a failure and its token cost stay on that job.

    The existing scorer drops CallMeta. The wrapper records the metadata returned
    by the real structured call and then calls that same function.
    """
    from jobhunt.core.claude import structured_call
    from jobhunt.fit import claude as claude_fit

    invoke = structured_call if invoke_model is None else invoke_model
    captured: list[Any] = []
    captured_matches: list[list[Any]] = []

    def recording(**kwargs: Any) -> tuple[Any, Any]:
        parsed, meta = invoke(**kwargs)
        captured.append(meta)
        captured_matches.append(list(getattr(parsed, "matches", ())))
        return parsed, meta

    module: Any = claude_fit
    previous = module.structured_call
    module.structured_call = recording
    try:
        outcomes: list[CandidateOutcome] = []
        for job in jobs:
            before = len(captured)
            started = time.perf_counter()
            result: FitResult | None = None
            error: str | None = None
            try:
                result = scorer.fit(docs, job.scored_text)
            except FitUnavailable as exc:
                error = str(exc)
            elapsed_ms = (time.perf_counter() - started) * 1000
            calls = captured[before:]
            replies = captured_matches[before:]
            last_matches = replies[-1] if replies and result is not None else []
            outcomes.append(
                CandidateOutcome(
                    job_id=job.job_id,
                    result=result,
                    error=error,
                    latency_ms=elapsed_ms,
                    cost_usd=sum((call.cost_usd for call in calls), Decimal("0")),
                    input_tokens=sum(int(call.input_tokens) for call in calls),
                    output_tokens=sum(int(call.output_tokens) for call in calls),
                    matches=tuple(
                        (int(match.aspect_index), str(match.brag_doc_id), float(match.similarity))
                        for match in last_matches
                    ),
                )
            )
            if progress:
                print(
                    f"candidate {len(outcomes)}/{len(jobs)} job {job.job_id} "
                    f"{'error' if error else 'ok'}",
                    file=sys.stderr,
                )
        return outcomes
    finally:
        module.structured_call = previous


def read_population(conn: Any, *, model_id: str, source_hash: str) -> list[PopulationJob]:
    fit_rows = conn.execute(_FITS_SQL, (model_id, source_hash)).fetchall()
    match_rows = conn.execute(_MATCHES_SQL, (model_id, source_hash)).fetchall()
    grouped: dict[int, list[tuple[str, str, float]]] = {}
    for job_id, doc_ref, aspect, similarity in match_rows:
        grouped.setdefault(int(job_id), []).append((str(doc_ref), str(aspect), float(similarity)))
    jobs: list[PopulationJob] = []
    for job_id, title, description, score, raw, coverage, gaps in fit_rows:
        jobs.append(
            PopulationJob(
                job_id=int(job_id),
                title=str(title),
                scored_text=description if description else str(title),
                score=float(score),
                raw=float(raw),
                coverage=0.0 if coverage is None else float(coverage),
                gaps=tuple(str(gap) for gap in gaps or []),
                matches=tuple(grouped.get(int(job_id), [])),
            )
        )
    return jobs


def execute_sample(conn: Any, *, n: int, seed: int, mode: str, out: Path) -> str:
    """Read stored scores, call the existing Claude scorer, and freeze the artifacts."""
    from jobhunt.composition import require_on_machine
    from jobhunt.fit.claude import ClaudeFitScorer
    from jobhunt.fit.matrix import QWEN3
    from jobhunt.fit.sources import current_docs, docs_hash

    if (out / RAW_JSON).exists():
        raise BenchmarkError(f"raw result is already frozen at {out / RAW_JSON}")
    scorer = ClaudeFitScorer()
    require_on_machine(scorer, "fit scorer")
    conn.execute("SET TRANSACTION READ ONLY")
    docs = current_docs(conn, mode)
    source_hash = docs_hash(docs)
    population = read_population(conn, model_id=QWEN3.model_id, source_hash=source_hash)
    if not population:
        raise BenchmarkError(f"no stored {QWEN3.model_id} scores for the current {mode} source")
    selected = stratified_sample(population, n=n, seed=seed)
    outcomes = run_candidate(scorer, docs, selected, progress=True)
    raw, identity, packet = build_payload(
        seed=seed,
        mode=mode,
        source_hash=source_hash,
        baseline_model_id=QWEN3.model_id,
        candidate_model_id=scorer.model_id,
        docs=docs,
        selected=selected,
        outcomes=outcomes,
    )
    return write_run(out, raw=raw, identity=identity, packet=packet)


def rescore_frozen(source: Path, dest: Path) -> str:
    """Score the frozen jobs again and write a new raw file that records matches.

    Uses the docs and job text in `source`, not the live database. Does not
    change `source`.
    """
    from jobhunt.composition import require_on_machine
    from jobhunt.fit.claude import ClaudeFitScorer

    raw = load_json(source / RAW_JSON)
    docs = [BragDoc(id=str(doc["id"]), text=str(doc["text"])) for doc in raw["docs"]]
    selected = [_population_from_raw(job) for job in raw["jobs"]]
    scorer = ClaudeFitScorer()
    require_on_machine(scorer, "fit scorer")
    outcomes = run_candidate(scorer, docs, selected, progress=True)
    built, identity, packet = build_payload(
        seed=int(raw["seed"]),
        mode=str(raw["mode"]),
        source_hash=str(raw["source_hash"]),
        baseline_model_id=str(raw["baseline_model_id"]),
        candidate_model_id=scorer.model_id,
        docs=docs,
        selected=selected,
        outcomes=outcomes,
    )
    return write_run(dest, raw=built, identity=identity, packet=packet)


def _population_from_raw(job: Mapping[str, Any]) -> PopulationJob:
    baseline = job["baseline"]
    return PopulationJob(
        job_id=int(job["job_id"]),
        title=str(job["title"]),
        scored_text=str(job["scored_text"]),
        score=float(baseline["score"]),
        raw=float(baseline["raw"]),
        coverage=float(baseline["coverage"]),
        gaps=tuple(str(gap) for gap in baseline.get("gaps") or []),
        matches=tuple(
            (str(match["doc_id"]), str(match["aspect"]), float(match["similarity"]))
            for match in baseline.get("top_docs") or []
            if "aspect" in match and "similarity" in match
        ),
    )


def write_run(
    out: Path,
    *,
    raw: Mapping[str, Any],
    identity: Mapping[str, Any],
    packet: Mapping[str, Any],
) -> str:
    if (out / RAW_JSON).exists():
        raise BenchmarkError(f"raw result is already frozen at {out / RAW_JSON}")
    _write_json(out / RAW_JSON, raw)
    digest = hashlib.sha256((out / RAW_JSON).read_bytes()).hexdigest()
    (out / RAW_DIGEST).write_text(f"{digest}  {RAW_JSON}\n", encoding="utf-8")
    (out / RAW_MARKDOWN).write_text(render_raw_markdown(raw), encoding="utf-8")
    _write_json(out / IDENTITY_JSON, identity)
    _write_json(out / BLIND_JSON, packet)
    rubric_path = out / RUBRIC_MARKDOWN
    rubric_path.parent.mkdir(parents=True, exist_ok=True)
    rubric_path.write_text(rubric_markdown(), encoding="utf-8")
    (out / "reviews").mkdir(exist_ok=True)
    return digest


def assert_frozen(out: Path) -> str:
    recorded = (out / RAW_DIGEST).read_text(encoding="utf-8").split()[0]
    actual = hashlib.sha256((out / RAW_JSON).read_bytes()).hexdigest()
    if recorded != actual:
        raise BenchmarkError("raw result digest does not match the frozen file")
    return actual


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise BenchmarkError(f"{path.name} must be a JSON object")
    return payload


def load_review(path: Path) -> JudgeReview:
    if not path.is_file():
        raise BenchmarkError(f"no judge review at {path}")
    return parse_judge_review(load_json(path))


def render_report(out: Path) -> str:
    """Summarize the frozen sample and each judge. Recommendations stay separate."""
    assert_frozen(out)
    raw = load_json(out / RAW_JSON)
    identity = load_json(out / IDENTITY_JSON)
    lines = [render_raw_markdown(raw).rstrip(), ""]
    reviews: dict[str, JudgeReview] = {}
    for label, relative in (("opus", OPUS_JSON), ("sol", SOL_JSON)):
        path = out / relative
        if not path.is_file():
            lines.append(f"{label}: no review")
            continue
        review = load_review(path)
        reviews[label] = review
        metrics = judge_metrics(raw["jobs"], identity, review)
        lines.extend(_judge_lines(label, metrics))
    if len(reviews) == 2:
        cases = queue_cases(raw["jobs"], identity, reviews["opus"], reviews["sol"])
        queued = review_queue(cases, limit=20, seed=int(raw["seed"]))
        listed = ", ".join(str(job_id) for job_id in queued)
        lines.append(f"human queue: {listed}")
    lines.append("Judges are reported separately.")
    return "\n".join(lines) + "\n"


def _judge_lines(label: str, metrics: Mapping[str, Any]) -> list[str]:
    wilson = metrics["wilson95"]
    lower = None if wilson is None else wilson[0]
    upper = None if wilson is None else wilson[1]
    return [
        f"{label}: recommendation {metrics['recommendation']}",
        (
            f"  candidate win rate {_plain(metrics['candidate_win_rate'])} "
            f"decisive {metrics['decisive']} ties {metrics['ties']} missing {metrics['missing']}"
        ),
        f"  wilson95 {_plain(lower)} to {_plain(upper)}",
        (
            f"  spearman baseline {_plain(metrics['spearman_baseline'])} "
            f"candidate {_plain(metrics['spearman_candidate'])}"
        ),
        (
            f"  hit@10 baseline {_plain(metrics['hit_at_10_baseline'])} "
            f"candidate {_plain(metrics['hit_at_10_candidate'])}"
        ),
    ]


def _job_record(
    job: PopulationJob,
    outcome: CandidateOutcome,
    doc_text: Mapping[str, str],
) -> dict[str, Any]:
    from jobhunt.fit.aspects import split_aspects

    cited = [match[0] for match in job.matches]
    if outcome.result is not None:
        cited.extend(match.brag_doc_id for match in outcome.result.top_docs)
    return {
        "job_id": job.job_id,
        "title": job.title,
        "scored_text": job.scored_text,
        "aspects": split_aspects(job.scored_text),
        "evidence": _evidence(cited, doc_text),
        "baseline": _baseline_side(job),
        "candidate": _candidate_side(outcome),
        "error": outcome.error if outcome.result is None else None,
        "latency_ms": round(outcome.latency_ms, 3),
        "cost_usd": format(outcome.cost_usd, "f"),
        "input_tokens": outcome.input_tokens,
        "output_tokens": outcome.output_tokens,
    }


def _baseline_side(job: PopulationJob) -> dict[str, Any]:
    return {
        "score": job.score,
        "raw": job.raw,
        "coverage": job.coverage,
        "tier": job.tier,
        "top_docs": [
            {"doc_id": doc_id, "aspect": aspect, "similarity": similarity}
            for doc_id, aspect, similarity in job.matches
        ],
        "gaps": list(job.gaps),
    }


def _candidate_side(outcome: CandidateOutcome) -> dict[str, Any] | None:
    if outcome.result is None:
        return None
    result = outcome.result
    return {
        "score": result.score,
        "raw": result.raw,
        "coverage": result.coverage,
        "tier": tier(result.score),
        "top_docs": [
            {
                "doc_id": match.brag_doc_id,
                "aspect": match.aspect,
                "similarity": match.similarity,
            }
            for match in result.top_docs
        ],
        "gaps": list(result.gaps),
        "matches": [
            {"aspect_index": index, "doc_id": doc_id, "similarity": similarity}
            for index, doc_id, similarity in outcome.matches
        ],
    }


def replay_evidence(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Recompute v3 scores from recorded matches. Does not call a model.

    A job with no `matches` key cannot be replayed. An empty match list is a
    real reply and scores from that.
    """
    from jobhunt.fit.base import BragDoc
    from jobhunt.fit.claude import (
        MIN_ASPECTS,
        AspectMatch,
        MatchFields,
        clean_aspects,
        evidence_result,
    )

    docs = [BragDoc(id=str(doc["id"]), text=str(doc["text"])) for doc in raw["docs"]]
    rows: list[dict[str, Any]] = []
    for job in raw["jobs"]:
        candidate = job.get("candidate") or {}
        if "matches" not in candidate:
            rows.append({"job_id": int(job["job_id"]), "score": None, "replayed": False})
            continue
        aspects = clean_aspects(str(job["scored_text"]))
        if len(aspects) < MIN_ASPECTS:
            rows.append(
                {"job_id": int(job["job_id"]), "score": 0.0, "coverage": 0.0, "replayed": True}
            )
            continue
        parsed = MatchFields(
            matches=[
                AspectMatch(
                    aspect_index=int(match["aspect_index"]),
                    brag_doc_id=str(match["doc_id"]),
                    similarity=float(match["similarity"]),
                )
                for match in candidate["matches"]
            ]
        )
        result = evidence_result(parsed, docs, aspects)
        rows.append(
            {
                "job_id": int(job["job_id"]),
                "score": result.score,
                "coverage": result.coverage,
                "replayed": True,
            }
        )
    return rows


def replay_report(out: Path, reviews: Path | None = None) -> dict[str, Any]:
    """Spearman of replayed scores against the frozen judge ratings.

    `reviews` defaults to `out`. Returns missing_matches when the raw file has
    no recorded match lists. Does not call a model and does not write.
    """
    from jobhunt.fit.calibrate import tier
    from jobhunt.fit.eval import spearman

    raw = load_json(out / RAW_JSON)
    rows = replay_evidence(raw)
    missing = [row for row in rows if not row["replayed"]]
    usable = [row for row in rows if row["replayed"]]
    report: dict[str, Any] = {
        "jobs": len(rows),
        "replayed": len(usable),
        "missing_matches": len(missing),
    }
    scores = {int(row["job_id"]): float(row["score"]) for row in usable}
    coverage_of = {int(row["job_id"]): float(row["coverage"]) for row in usable}
    if not scores:
        return report
    fair_without_coverage = sum(
        1 for job_id, score in scores.items() if coverage_of[job_id] < 0.1 and tier(score) != "low"
    )
    report["fair_or_better_with_coverage_under_0_1"] = fair_without_coverage
    review_root = out if reviews is None else reviews
    for label, relative in (("opus", OPUS_JSON), ("sol", SOL_JSON)):
        path = review_root / relative
        if not path.is_file():
            report[f"spearman_{label}"] = None
            continue
        ratings = {int(job["job_id"]): float(job["rating"]) for job in load_json(path)["jobs"]}
        shared = [job_id for job_id in scores if job_id in ratings]
        report[f"spearman_{label}"] = spearman(
            [scores[job_id] for job_id in shared],
            [ratings[job_id] for job_id in shared],
        )
        high = [
            job_id for job_id in shared if ratings[job_id] >= 4 and tier(scores[job_id]) == "low"
        ]
        report[f"rated_4_or_5_in_low_{label}"] = high
    return report


def _public_side(side: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if side is None:
        return None
    return {
        "score": side["score"],
        "coverage": side["coverage"],
        "tier": side["tier"],
        "top_docs": side["top_docs"],
        "gaps": side["gaps"],
    }


def _public_candidate(job: Mapping[str, Any]) -> dict[str, Any] | None:
    candidate = job.get("candidate")
    if candidate is None:
        return None
    return _public_side(candidate)


def _evidence(doc_ids: Sequence[str], doc_text: Mapping[str, str]) -> list[dict[str, str]]:
    seen: set[str] = set()
    rows: list[dict[str, str]] = []
    for doc_id in doc_ids:
        if doc_id in seen:
            continue
        seen.add(doc_id)
        rows.append({"id": doc_id, "text": doc_text.get(doc_id, "")})
    return rows


def _collect_secondary(
    job: Mapping[str, Any],
    item: JobJudgment,
    ratings: list[float],
    baseline_scores: list[float],
    candidate_scores: list[float],
    baseline_docs: list[list[str]],
    candidate_docs: list[list[str]],
    expected_docs: list[list[str]],
) -> None:
    candidate = job.get("candidate")
    if candidate is None:
        return
    ratings.append(float(item.rating))
    baseline_scores.append(float(job["baseline"]["score"]))
    candidate_scores.append(float(candidate["score"]))
    if not item.expected_docs:
        return
    expected_docs.append(list(item.expected_docs))
    baseline_docs.append([str(match["doc_id"]) for match in job["baseline"]["top_docs"]])
    candidate_docs.append([str(match["doc_id"]) for match in candidate["top_docs"]])


def _ordered_for_review(cases: Any) -> list[QueueCase]:
    return sorted(cases, key=lambda case: (-_tier_distance(case), -_abs_delta(case), case.job_id))


def _needs_decision(case: QueueCase) -> bool:
    if case.opus_preference is None or case.sol_preference is None:
        return True
    return case.opus_preference != case.sol_preference


def _is_low_confidence(case: QueueCase) -> bool:
    if _needs_decision(case):
        return False
    confidences = [case.opus_confidence, case.sol_confidence]
    return any(value is not None and value < LOW_CONFIDENCE for value in confidences)


def _is_agreement(case: QueueCase) -> bool:
    return (
        case.opus_preference is not None
        and case.opus_preference == case.sol_preference
        and not _is_low_confidence(case)
    )


def _tier_distance(case: QueueCase) -> int:
    if case.candidate_tier is None:
        return len(TIERS)
    return abs(_TIER_INDEX[case.baseline_tier] - _TIER_INDEX[case.candidate_tier])


def _abs_delta(case: QueueCase) -> float:
    if case.score_delta is None:
        return 100.0
    return abs(case.score_delta)


def _shuffled(jobs: Sequence[PopulationJob], seed: str) -> list[PopulationJob]:
    ordered = sorted(jobs, key=lambda job: job.job_id)
    random.Random(seed).shuffle(ordered)
    return ordered


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _plain(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
