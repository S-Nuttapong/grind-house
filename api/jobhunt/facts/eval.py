"""Score a parser against labeled cases. The caller passes the parser object."""

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import quantiles
from typing import Any

from jobhunt.core.paths import API_ROOT
from jobhunt.facts.base import FIELDS, FieldName, JobDetail, PostingInput
from jobhunt.facts.contract import check_facts

_JUDGED: tuple[FieldName, ...] = ("role", "level", "locations", "pay", "job_type", "workplace")
CACHE_DIR = API_ROOT / "evals" / "cache"


@dataclass(frozen=True)
class ParserCase:
    case_id: str
    posting: PostingInput
    expected: JobDetail


@dataclass
class FieldScore:
    correct: int = 0
    missing: int = 0
    wrong: int = 0
    hallucinated: int = 0

    def add(self, outcome: str) -> None:
        setattr(self, outcome, getattr(self, outcome) + 1)

    @property
    def predicted(self) -> int:
        return self.correct + self.wrong + self.hallucinated

    @property
    def labeled(self) -> int:
        return self.correct + self.wrong + self.missing


@dataclass
class ParserReport:
    fields: dict[str, FieldScore] = field(default_factory=dict)
    schema_valid: int = 0
    errors: int = 0
    cases: int = 0
    latencies: list[float] = field(default_factory=list)
    cost_usd: float = 0.0
    confidences: list[tuple[float, bool]] = field(default_factory=list)

    @property
    def precision(self) -> float | None:
        return _ratio(_total(self, "correct"), _total(self, "predicted"))

    @property
    def recall(self) -> float | None:
        return _ratio(_total(self, "correct"), _total(self, "labeled"))

    @property
    def hallucination(self) -> float | None:
        judged = sum(score.labeled + score.hallucinated for score in self.fields.values())
        return _ratio(_total(self, "hallucinated"), judged)

    @property
    def schema_valid_rate(self) -> float | None:
        return _ratio(self.schema_valid, self.cases)

    @property
    def ece(self) -> float | None:
        return _ece(self.confidences)


def eval_parser(
    parser: object,
    cases: list[ParserCase],
    *,
    cache_dir: Path | None = CACHE_DIR,
) -> ParserReport:
    """Score `parser` on `cases`. A cache hit is not called again."""
    report = ParserReport(fields={name: FieldScore() for name in _JUDGED})
    report.cases = len(cases)
    seen = len(getattr(parser, "calls", []))
    for case in cases:
        started = time.perf_counter()
        detail, failed = _parse(parser, case, cache_dir)
        report.latencies.append(time.perf_counter() - started)
        if failed:
            report.errors += 1
            continue
        report.schema_valid += 1
        checked = check_facts(
            detail, title=case.posting.title, description=case.posting.description_md
        )
        _score_case(report, case.expected, checked)
    report.cost_usd = _new_cost(parser, seen)
    return report


def parser_gates(report: ParserReport) -> list[str]:
    """Empty when hallucination, precision, and schema validity all pass."""
    failures: list[str] = []
    if report.hallucination is None or report.hallucination > 0.02:
        failures.append("hallucination above 2%")
    if report.precision is None or report.precision < 0.95:
        failures.append("precision below 0.95")
    if report.schema_valid_rate is None or report.schema_valid_rate < 0.995:
        failures.append("schema-valid below 99.5%")
    return failures


def latency_p50(report: ParserReport) -> float | None:
    return _percentile(report.latencies, 50)


def latency_p95(report: ParserReport) -> float | None:
    return _percentile(report.latencies, 95)


def load_gold(path: Path) -> list[ParserCase]:
    cases: list[ParserCase] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        cases.append(_case(json.loads(line)))
    return cases


def write_gold(path: Path, cases: list[ParserCase]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [_dump(case) for case in cases]
    path.write_text("\n".join(lines) + ("\n" if lines else ""))


def _parse(parser: object, case: ParserCase, cache_dir: Path | None) -> tuple[JobDetail, bool]:
    cached = _read_cache(parser, case, cache_dir)
    if cached is not None:
        return cached
    try:
        detail = parser.parse(case.posting)  # type: ignore[attr-defined]
    except Exception:
        _write_cache(parser, case, cache_dir, None, failed=True)
        return JobDetail(), True
    if not isinstance(detail, JobDetail):
        _write_cache(parser, case, cache_dir, None, failed=True)
        return JobDetail(), True
    _write_cache(parser, case, cache_dir, detail, failed=False)
    return detail, False


def _score_case(report: ParserReport, expected: JobDetail, predicted: JobDetail) -> None:
    for name in _JUDGED:
        outcome = _judge(_present(expected, name), _present(predicted, name))
        if outcome is None:
            continue
        report.fields[name].add(outcome)
        fact = _fact(predicted, name)
        if fact is not None and outcome in {"correct", "wrong", "hallucinated"}:
            report.confidences.append((float(fact.confidence), outcome == "correct"))


def _judge(expected: str | None, predicted: str | None) -> str | None:
    if expected is None and predicted is None:
        return None
    if expected is None:
        return "hallucinated"
    if predicted is None:
        return "missing"
    if expected == predicted:
        return "correct"
    return "wrong"


def _present(detail: JobDetail, name: FieldName) -> str | None:
    fact = _fact(detail, name)
    if fact is None:
        return None
    if name == "pay":
        pay = fact.value
        return f"{pay.minimum}|{pay.maximum}|{pay.currency}|{pay.interval}"
    if name == "locations":
        if not fact.value:
            return None
        place = fact.value[0]
        return f"{place.country}|{place.city}"
    if name == "posted":
        return str(fact.value)
    return str(fact.value)


def _fact(detail: JobDetail, name: FieldName) -> Any:
    if name not in FIELDS:
        return None
    return getattr(detail, name)


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _total(report: ParserReport, kind: str) -> int:
    if kind == "predicted":
        return sum(score.predicted for score in report.fields.values())
    if kind == "labeled":
        return sum(score.labeled for score in report.fields.values())
    return sum(getattr(score, kind) for score in report.fields.values())


def _ece(pairs: list[tuple[float, bool]]) -> float | None:
    if not pairs:
        return None
    buckets: list[list[tuple[float, bool]]] = [[] for _index in range(10)]
    for confidence, correct in pairs:
        buckets[min(9, int(max(0.0, min(0.999, confidence)) * 10))].append((confidence, correct))
    error = 0.0
    for bucket in buckets:
        if not bucket:
            continue
        average_confidence = sum(item[0] for item in bucket) / len(bucket)
        average_accuracy = sum(1 for _confidence, correct in bucket if correct) / len(bucket)
        error += (len(bucket) / len(pairs)) * abs(average_accuracy - average_confidence)
    return error


def _percentile(values: list[float], percent: int) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return quantiles(values, n=100, method="inclusive")[percent - 1]


def _new_cost(parser: object, seen: int) -> float:
    calls = getattr(parser, "calls", [])
    return float(sum(call.cost_usd for call in calls[seen:]))


def _cache_path(parser: object, case: ParserCase, cache_dir: Path | None) -> Path | None:
    if cache_dir is None:
        return None
    parser_id = str(getattr(parser, "parser_id", type(parser).__name__))
    digest = hashlib.sha256(f"{parser_id}\n{case.posting.model_dump_json()}".encode()).hexdigest()
    return cache_dir / f"{digest}.json"


def _read_cache(
    parser: object, case: ParserCase, cache_dir: Path | None
) -> tuple[JobDetail, bool] | None:
    path = _cache_path(parser, case, cache_dir)
    if path is None or not path.is_file():
        return None
    payload = json.loads(path.read_text())
    if payload.get("failed"):
        return JobDetail(), True
    return JobDetail.model_validate(payload["detail"]), False


def _write_cache(
    parser: object,
    case: ParserCase,
    cache_dir: Path | None,
    detail: JobDetail | None,
    *,
    failed: bool,
) -> None:
    path = _cache_path(parser, case, cache_dir)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"failed": failed, "detail": None if detail is None else detail.model_dump(mode="json")}
    path.write_text(json.dumps(body))


def _case(payload: dict[str, object]) -> ParserCase:
    from decimal import Decimal

    from jobhunt.facts.base import LocationFact, Pay, PayFact, Place, TextFact

    def text(value: object, evidence: str) -> TextFact | None:
        if not isinstance(value, str) or not value:
            return None
        return TextFact(value=value, confidence=1, evidence=evidence, parser_id="gold")

    country = payload.get("country")
    city = payload.get("city")
    locations = None
    if isinstance(country, str) and country:
        locations = LocationFact(
            value=[Place(country=country, city=city if isinstance(city, str) and city else None)],
            confidence=1,
            evidence=str(payload.get("evidence_location") or country),
            parser_id="gold",
        )
    pay = None
    minimum = payload.get("pay_min")
    maximum = payload.get("pay_max")
    if minimum is not None or maximum is not None:
        pay = PayFact(
            value=Pay(
                minimum=None if minimum is None else Decimal(str(minimum)),
                maximum=None if maximum is None else Decimal(str(maximum)),
                currency=_text_or_none(payload.get("pay_currency")),
                interval=_text_or_none(payload.get("pay_interval")),
            ),
            confidence=1,
            evidence=str(payload.get("evidence_pay") or "pay"),
            parser_id="gold",
        )
    title = str(payload.get("title") or "")
    description = str(payload.get("description") or "")
    return ParserCase(
        case_id=str(payload["id"]),
        posting=PostingInput(title=title, description_md=description),
        expected=JobDetail(
            role=text(payload.get("role"), str(payload.get("evidence_role") or title)),
            level=text(payload.get("level"), str(payload.get("evidence_level") or title)),
            workplace=text(payload.get("workplace"), str(payload.get("evidence_workplace") or "")),
            job_type=text(payload.get("job_type"), str(payload.get("evidence_job_type") or "")),
            locations=locations,
            pay=pay,
        ),
    )


def _text_or_none(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _dump(case: ParserCase) -> str:
    expected = case.expected
    place = expected.locations.value[0] if expected.locations and expected.locations.value else None
    pay = expected.pay.value if expected.pay is not None else None
    return json.dumps(
        {
            "id": case.case_id,
            "title": case.posting.title,
            "description": case.posting.description_md,
            "role": None if expected.role is None else expected.role.value,
            "level": None if expected.level is None else expected.level.value,
            "country": None if place is None else place.country,
            "city": None if place is None else place.city,
            "workplace": None if expected.workplace is None else expected.workplace.value,
            "job_type": None if expected.job_type is None else expected.job_type.value,
            "pay_min": None if pay is None or pay.minimum is None else str(pay.minimum),
            "pay_max": None if pay is None or pay.maximum is None else str(pay.maximum),
            "pay_currency": None if pay is None else pay.currency,
            "pay_interval": None if pay is None else pay.interval,
        }
    )
