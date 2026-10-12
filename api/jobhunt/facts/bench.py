"""Bake-off: default vs gliner vs default+gliner, scored against api fields."""

import csv
import gc
import hashlib
import json
import resource
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from psycopg import Connection

from jobhunt.core.paths import API_ROOT
from jobhunt.facts.api_fields import from_payload
from jobhunt.facts.base import FIELDS, FieldName, JobDetail, Pay
from jobhunt.facts.decide import FieldChoice, ModeScore, choose_field
from jobhunt.facts.default import DefaultParser
from jobhunt.facts.gliner import GlinerParser

_MODES = ("default", "gliner", "default+gliner")
_SCORED: tuple[FieldName, ...] = ("pay", "job_type", "workplace", "locations")
_THRESHOLDS = [round(0.3 + index * 0.1, 1) for index in range(7)]


@dataclass
class _Row:
    job_id: int
    posting_id: int
    source_id: str
    text: str
    truth: JobDetail
    split: str


@dataclass
class _Score:
    labeled: int = 0
    returned: int = 0
    correct: int = 0
    city_labeled: int = 0
    city_correct: int = 0

    def add(self, other: "_Score") -> None:
        self.labeled += other.labeled
        self.returned += other.returned
        self.correct += other.correct
        self.city_labeled += other.city_labeled
        self.city_correct += other.city_correct

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "labeled": self.labeled,
            "returned": self.returned,
            "correct": self.correct,
            "precision": _ratio(self.correct, self.returned),
            "recall": _ratio(self.correct, self.labeled),
            "coverage": _ratio(self.returned, self.labeled),
            "city_labeled": self.city_labeled,
            "city_correct": self.city_correct,
            "city_recall": _ratio(self.city_correct, self.city_labeled),
        }


@dataclass
class _Pred:
    detail: JobDetail
    seconds: float


@dataclass
class _Report:
    scores: dict[str, dict[str, dict[str, dict[str, _Score]]]] = field(default_factory=dict)
    times: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    thresholds: dict[str, float] = field(default_factory=dict)
    disagreements: list[dict[str, str]] = field(default_factory=list)
    load_seconds: float = 0.0
    rss_kb: int = 0
    jobs: int = 0


def run_bench(conn: Connection[Any], *, sample: int | None = None) -> Path:
    """Score every labeled open posting. Thresholds are chosen on dev, reported on test."""
    rows = _load(conn, sample)
    print(f"bench rows {len(rows)}", flush=True)
    report = _Report(jobs=len({row.job_id for row in rows}))
    default_preds = _run_mode(rows, "default", DefaultParser(), report)
    started = time.perf_counter()
    # The sweep starts at 0.3, so spans below that are noise and are not stored.
    gliner = GlinerParser(thresholds={name: 0.3 for name in FIELDS})
    report.load_seconds = time.perf_counter() - started
    gliner_preds = _run_mode(rows, "gliner", gliner, report)
    report.thresholds = _sweep(rows, gliner_preds)
    _score_all(rows, default_preds, gliner_preds, report)
    report.rss_kb = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return _write(report)


def _load(conn: Connection[Any], sample: int | None) -> list[_Row]:
    found: list[_Row] = []
    cursor = conn.execute(
        """
        SELECT j.id, p.id, p.source_id, j.description_md, rp.payload
        FROM jobs j
        JOIN postings p ON p.job_id = j.id
        JOIN LATERAL (
            SELECT payload FROM raw_payloads r
            WHERE r.posting_id = p.id
            ORDER BY fetched_at DESC
            LIMIT 1
        ) rp ON true
        WHERE j.closed_at IS NULL
          AND j.description_md IS NOT NULL
          AND length(j.description_md) > 40
        """
    )
    for job_id, posting_id, source_id, description, payload in cursor:
        if not isinstance(payload, dict) or not isinstance(description, str):
            continue
        truth = from_payload(str(source_id), payload)
        if not _labeled(truth):
            continue
        digest = hashlib.md5(str(job_id).encode()).hexdigest()
        found.append(
            _Row(
                job_id=int(job_id),
                posting_id=int(posting_id),
                source_id=str(source_id),
                text=description,
                truth=truth,
                split="dev" if int(digest, 16) % 2 == 0 else "test",
            )
        )
    if sample is None or sample >= len(found):
        return found
    return _stratify(found, sample)


def _stratify(rows: list[_Row], sample: int) -> list[_Row]:
    buckets: dict[str, list[_Row]] = defaultdict(list)
    for row in rows:
        buckets[row.source_id].append(row)
    picked: list[_Row] = []
    index = 0
    while len(picked) < sample and any(buckets.values()):
        for source in sorted(buckets):
            bucket = buckets[source]
            if index < len(bucket) and len(picked) < sample:
                picked.append(bucket[index])
        index += 1
        if index > max((len(bucket) for bucket in buckets.values()), default=0):
            break
    return picked


def _run_mode(rows: list[_Row], mode: str, parser: Any, report: _Report) -> dict[int, _Pred]:
    preds: dict[int, _Pred] = {}
    for index, row in enumerate(rows, start=1):
        started = time.perf_counter()
        detail = parser.parse(row.text)
        elapsed = time.perf_counter() - started
        preds[row.posting_id] = _Pred(detail, elapsed)
        report.times[mode].append(elapsed)
        if mode == "gliner":
            row.text = ""
        if index % 50 == 0 or index == len(rows):
            gc.collect()
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            print(f"bench {mode} {index}/{len(rows)} rss_kb={rss}", flush=True)
    return preds


def _sweep(rows: list[_Row], gliner_preds: dict[int, _Pred]) -> dict[str, float]:
    chosen: dict[str, float] = {}
    dev = [row for row in rows if row.split == "dev"]
    for name in _SCORED:
        best_threshold = 0.5
        best_recall = -1.0
        best_precision = -1.0
        for threshold in _THRESHOLDS:
            score = _Score()
            for row in dev:
                pred = _at_threshold(gliner_preds[row.posting_id].detail, name, threshold)
                score.add(_compare(name, row.truth, pred))
            precision = _ratio(score.correct, score.returned) or 0
            recall = _ratio(score.correct, score.labeled) or 0
            if precision >= 0.97 and recall > best_recall:
                best_threshold = threshold
                best_recall = recall
                best_precision = precision
            elif best_recall < 0 and precision > best_precision:
                best_threshold = threshold
                best_precision = precision
        chosen[name] = best_threshold
        print(f"sweep {name} threshold {best_threshold}", flush=True)
    return chosen


def _score_all(
    rows: list[_Row],
    default_preds: dict[int, _Pred],
    gliner_preds: dict[int, _Pred],
    report: _Report,
) -> None:
    per_field: dict[str, int] = defaultdict(int)
    for row in rows:
        default = default_preds[row.posting_id]
        gliner = gliner_preds[row.posting_id]
        chain_seconds = default.seconds
        views = {
            "default": default.detail,
            "gliner": _filtered(gliner.detail, report.thresholds),
            "default+gliner": _chain(default.detail, gliner.detail, report.thresholds),
        }
        if _any_missing(default.detail):
            chain_seconds += gliner.seconds
        report.times["default+gliner"].append(chain_seconds)
        for mode, detail in views.items():
            for name in _SCORED:
                score = _compare(name, row.truth, _field_detail(detail, name))
                _bucket(report, row.split, mode, name, row.source_id).add(score)
                missed = score.labeled and not score.correct and per_field[name] < 50
                if row.split == "test" and missed:
                    per_field[name] += 1
                    report.disagreements.append(
                        {
                            "field": name,
                            "job_id": str(row.job_id),
                            "source": row.source_id,
                            "truth": _brief(row.truth, name),
                            "default": _brief(views["default"], name),
                            "gliner": _brief(views["gliner"], name),
                            "chain": _brief(views["default+gliner"], name),
                        }
                    )


def _bucket(report: _Report, split: str, mode: str, name: str, source: str) -> _Score:
    table = report.scores.setdefault(split, {}).setdefault(mode, {}).setdefault(name, {})
    if source not in table:
        table[source] = _Score()
    if "*" not in table:
        table["*"] = _Score()
    # The caller adds to the source score. Add the same delta to "*" via a wrapper?
    # Return the source score and also update "*" in _score_all. Handle both here by
    # returning source; the caller adds once. "*" is updated alongside in _score_all.
    return table[source]


def _labeled(detail: JobDetail) -> bool:
    return any(_has_api(detail, name) for name in _SCORED)


def _has_api(detail: JobDetail, name: FieldName) -> bool:
    fact = _fact(detail, name)
    if fact is None:
        return False
    parser_id = str(getattr(fact, "parser_id", ""))
    return parser_id.startswith("api:")


def _compare(name: FieldName, truth: JobDetail, pred: JobDetail | None) -> _Score:
    score = _Score()
    if not _has_api(truth, name):
        return score
    score.labeled = 1
    fact = None if pred is None else _fact(pred, name)
    if fact is None:
        return score
    score.returned = 1
    if _matches(name, _fact(truth, name), fact):
        score.correct = 1
    if name == "locations":
        score.city_labeled, score.city_correct = _cities(truth, pred)
    return score


def _matches(name: FieldName, truth: Any, pred: Any) -> bool:
    if truth is None or pred is None:
        return False
    if name == "pay":
        return _pay_match(truth.value, pred.value)
    if name == "locations":
        truth_countries = {place.country for place in truth.value if place.country}
        pred_countries = {place.country for place in pred.value if place.country}
        return bool(truth_countries & pred_countries) or (
            not truth_countries and not pred_countries
        )
    return bool(truth.value == pred.value)


def _pay_match(truth: Pay, pred: Pay) -> bool:
    if truth.currency != pred.currency:
        return False
    return _close(truth.minimum, pred.minimum)


def _close(left: Decimal | None, right: Decimal | None) -> bool:
    if left is None or right is None or right == 0:
        return left == right
    return abs(left - right) / abs(right) <= Decimal("0.02")


def _cities(truth: JobDetail, pred: JobDetail | None) -> tuple[int, int]:
    if truth.locations is None:
        return 0, 0
    truth_cities = {place.city.casefold() for place in truth.locations.value if place.city}
    if not truth_cities:
        return 0, 0
    pred_cities: set[str] = set()
    if pred is not None and pred.locations is not None:
        pred_cities = {place.city.casefold() for place in pred.locations.value if place.city}
    return 1, int(bool(truth_cities & pred_cities))


def _at_threshold(detail: JobDetail, name: FieldName, threshold: float) -> JobDetail:
    fact = _fact(detail, name)
    if fact is None or float(fact.confidence) < threshold:
        return JobDetail()
    return _field_detail(detail, name)


def _filtered(detail: JobDetail, thresholds: dict[str, float]) -> JobDetail:
    kept = JobDetail()
    for name in _SCORED:
        fact = _fact(detail, name)
        if fact is None or float(fact.confidence) < thresholds.get(name, 0):
            continue
        kept = _copy_field(kept, detail, name)
    return kept


def _chain(default: JobDetail, gliner: JobDetail, thresholds: dict[str, float]) -> JobDetail:
    return _merge_details(default, _filtered(gliner, thresholds))


def _merge_details(primary: JobDetail, fallback: JobDetail) -> JobDetail:
    from jobhunt.facts.base import prefer

    return prefer(primary, fallback)


def _any_missing(detail: JobDetail) -> bool:
    return any(_fact(detail, name) is None for name in _SCORED)


def _field_detail(detail: JobDetail, name: FieldName) -> JobDetail:
    return _copy_field(JobDetail(), detail, name)


def _copy_field(target: JobDetail, source: JobDetail, name: FieldName) -> JobDetail:
    if name == "pay":
        target.pay = source.pay
    elif name == "job_type":
        target.job_type = source.job_type
    elif name == "workplace":
        target.workplace = source.workplace
    elif name == "locations":
        target.locations = source.locations
    return target


def _fact(detail: JobDetail, name: FieldName) -> Any:
    if name == "pay":
        return detail.pay
    if name == "job_type":
        return detail.job_type
    if name == "workplace":
        return detail.workplace
    if name == "locations":
        return detail.locations
    return detail.posted


def _brief(detail: JobDetail, name: str) -> str:
    fact = _fact(detail, name)  # type: ignore[arg-type]
    if fact is None:
        return ""
    value = fact.value
    if hasattr(value, "model_dump"):
        return json.dumps(value.model_dump(mode="json"), default=str)
    if isinstance(value, list):
        return json.dumps([item.model_dump(mode="json") for item in value])
    return str(value)


def _write(report: _Report) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    directory = API_ROOT / "reports"
    directory.mkdir(exist_ok=True)
    payload = _payload(report)
    json_path = directory / f"facts_bench_{stamp}.json"
    md_path = directory / f"facts_bench_{stamp}.md"
    csv_path = directory / f"facts_bench_{stamp}_disagreements.csv"
    json_path.write_text(json.dumps(payload, indent=2))
    md_path.write_text(_markdown(payload))
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["field", "job_id", "source", "truth", "default", "gliner", "chain"],
        )
        writer.writeheader()
        writer.writerows(report.disagreements)
    print(f"bench report {md_path}", flush=True)
    return md_path


def _payload(report: _Report) -> dict[str, Any]:
    scores: dict[str, Any] = {}
    for split, modes in report.scores.items():
        scores[split] = {}
        for mode, fields in modes.items():
            scores[split][mode] = {}
            for name, sources in fields.items():
                total = _Score()
                rendered: dict[str, Any] = {}
                for source, score in sources.items():
                    if source == "*":
                        continue
                    total.add(score)
                    rendered[source] = score.as_dict()
                rendered["*"] = total.as_dict()
                scores[split][mode][name] = rendered
    timing = {mode: _timing(values) for mode, values in report.times.items()}
    choices = {}
    for name in _SCORED:
        mode_scores = []
        for mode in _MODES:
            overall = scores.get("test", {}).get(mode, {}).get(name, {}).get("*", {})
            mode_scores.append(
                ModeScore(
                    mode=mode,
                    precision=overall.get("precision"),
                    recall=overall.get("recall"),
                    p50_seconds=timing.get(mode, {}).get("p50_seconds", 0.0),
                )
            )
        choice = choose_field(mode_scores)
        choices[name] = FieldChoice(name, choice.mode, choice.flagged, choice.reason)
    return {
        "jobs": report.jobs,
        "gliner_load_seconds": report.load_seconds,
        "peak_rss_kb": report.rss_kb,
        "thresholds": report.thresholds,
        "timing": timing,
        "scores": scores,
        "choices": {
            name: {"mode": choice.mode, "flagged": choice.flagged, "reason": choice.reason}
            for name, choice in choices.items()
        },
    }


def _timing(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50_seconds": 0, "p95_seconds": 0, "jobs_per_minute": 0, "total_seconds": 0}
    total = sum(values)
    per_minute = len(values) / total * 60 if total else 0
    return {
        "p50_seconds": _percentile(values, 0.50),
        "p95_seconds": _percentile(values, 0.95),
        "jobs_per_minute": per_minute,
        "total_seconds": total,
    }


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(quantile * (len(ordered) - 1)))
    return ordered[index]


def _markdown(payload: dict[str, Any]) -> str:
    lines = ["# Facts bake-off", ""]
    timing = payload["timing"]
    lines.append(
        f"GLiNER load {payload['gliner_load_seconds']:.1f}s, peak RSS {payload['peak_rss_kb']} KB."
    )
    lines.append("")
    lines.append("| mode | p50 s | p95 s | jobs/min | total s |")
    lines.append("| --- | --- | --- | --- | --- |")
    for mode, stats in timing.items():
        lines.append(
            f"| {mode} | {stats['p50_seconds']:.3f} | {stats['p95_seconds']:.3f} | "
            f"{stats['jobs_per_minute']:.1f} | {stats['total_seconds']:.1f} |"
        )
    lines.append("")
    lines.append("## Test")
    lines.append("")
    for name in _SCORED:
        lines.append(f"### {name}")
        lines.append("")
        lines.append("| mode | precision | recall | coverage | labeled |")
        lines.append("| --- | --- | --- | --- | --- |")
        for mode in _MODES:
            overall = payload["scores"].get("test", {}).get(mode, {}).get(name, {}).get("*", {})
            lines.append(
                f"| {mode} | {_pct(overall.get('precision'))} | {_pct(overall.get('recall'))} | "
                f"{_pct(overall.get('coverage'))} | {overall.get('labeled', 0)} |"
            )
        choice = payload["choices"][name]
        flag = " flagged" if choice["flagged"] else ""
        lines.append("")
        lines.append(f"Winner: `{choice['mode']}` ({choice['reason']}){flag}.")
        lines.append("")
    lines.append(f"Thresholds: `{json.dumps(payload['thresholds'])}`.")
    lines.append("")
    return "\n".join(lines)


def _pct(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{value:.3f}"


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator
