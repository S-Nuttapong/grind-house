"""Fit metrics. eval_fit takes a scorer, not a model name."""

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

from jobhunt.fit.base import BragDoc, FitScorer


def spearman(left: Sequence[float], right: Sequence[float]) -> float | None:
    """Rank correlation. None when either side does not vary or there is one pair."""
    if len(left) != len(right) or len(left) < 2:
        return None
    return _pearson(_ranks(left), _ranks(right))


def quadratic_kappa(
    left: Sequence[int], right: Sequence[int], *, categories: int = 5
) -> float | None:
    """Quadratic weighted kappa. None when there are no pairs."""
    if len(left) != len(right) or not left:
        return None
    observed = [[0.0 for _column in range(categories)] for _row in range(categories)]
    for first, second in zip(left, right, strict=True):
        observed[first - 1][second - 1] += 1
    count = float(len(left))
    row_sum = [sum(row) for row in observed]
    column_sum = [
        sum(observed[row][column] for row in range(categories)) for column in range(categories)
    ]
    denominator = (categories - 1) ** 2
    weighted_observed = 0.0
    weighted_expected = 0.0
    for row in range(categories):
        for column in range(categories):
            weight = ((row - column) ** 2) / denominator
            weighted_observed += weight * observed[row][column]
            weighted_expected += weight * (row_sum[row] * column_sum[column] / count)
    if weighted_expected == 0:
        return 1.0
    return 1 - (weighted_observed / weighted_expected)


def icc(measures: Sequence[Sequence[float]]) -> float | None:
    """One-way ICC. Each inner list is the repeated scores for one item."""
    rows = [list(row) for row in measures if len(row) >= 2]
    if len(rows) < 2:
        return None
    reps = len(rows[0])
    if any(len(row) != reps for row in rows):
        return None
    grand = sum(sum(row) for row in rows) / (len(rows) * reps)
    between = reps * sum((sum(row) / reps - grand) ** 2 for row in rows) / (len(rows) - 1)
    within_sum = sum(sum((value - sum(row) / reps) ** 2 for value in row) for row in rows)
    within = within_sum / (len(rows) * (reps - 1))
    bottom = between + (reps - 1) * within
    if bottom == 0:
        return 1.0
    return (between - within) / bottom


def retest_sd(measures: Sequence[Sequence[float]]) -> float | None:
    """Mean within-item standard deviation. None when nothing was repeated."""
    spreads: list[float] = []
    for row in measures:
        if len(row) < 2:
            continue
        mean = sum(row) / len(row)
        variance = sum((value - mean) ** 2 for value in row) / (len(row) - 1)
        spreads.append(math.sqrt(variance))
    if not spreads:
        return None
    return sum(spreads) / len(spreads)


def hit_at_k(
    chosen: Sequence[Sequence[str]], expected: Sequence[Sequence[str]], k: int
) -> float | None:
    """Share of labeled jobs whose expected docs include one of the top k picks."""
    pairs = [(picks, wanted) for picks, wanted in zip(chosen, expected, strict=True) if wanted]
    if not pairs:
        return None
    hits = sum(1 for picks, wanted in pairs if any(doc in picks[:k] for doc in wanted))
    return hits / len(pairs)


def precision_at_k(
    chosen: Sequence[Sequence[str]], expected: Sequence[Sequence[str]], k: int
) -> float | None:
    """Share of the top-k picks that are in the expected docs. None when nothing was picked."""
    hits = 0
    total = 0
    for picks, wanted in zip(chosen, expected, strict=True):
        top = list(picks[:k])
        wanted_set = set(wanted)
        total += len(top)
        hits += sum(1 for doc in top if doc in wanted_set)
    if total == 0:
        return None
    return hits / total


def recall_at_k(
    chosen: Sequence[Sequence[str]], expected: Sequence[Sequence[str]], k: int
) -> float | None:
    """Share of the expected docs that appear in the top k. None when nothing was expected."""
    hits = 0
    total = 0
    for picks, wanted in zip(chosen, expected, strict=True):
        if not wanted:
            continue
        top = set(picks[:k])
        total += len(wanted)
        hits += sum(1 for doc in wanted if doc in top)
    if total == 0:
        return None
    return hits / total


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        average = (start + 1 + end + 1) / 2
        for position in range(start, end + 1):
            ranks[order[position]] = average
        start = end + 1
    return ranks


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    count = len(left)
    mean_left = sum(left) / count
    mean_right = sum(right) / count
    numerator = sum(
        (x_value - mean_left) * (y_value - mean_right)
        for x_value, y_value in zip(left, right, strict=True)
    )
    spread_left = math.sqrt(sum((value - mean_left) ** 2 for value in left))
    spread_right = math.sqrt(sum((value - mean_right) ** 2 for value in right))
    if spread_left == 0 or spread_right == 0:
        return None
    return float(numerator / (spread_left * spread_right))


@dataclass(frozen=True)
class FitLabel:
    description: str
    rating: float
    docs: tuple[str, ...] = ()


@dataclass(frozen=True)
class FitReport:
    spearman: float | None
    hit_at_10: float | None
    kappa: float | None
    icc: float | None
    retest_sd: float | None
    order_delta: float | None
    precision_at_10: float | None = None
    recall_at_10: float | None = None


@dataclass(frozen=True)
class BootstrapJob:
    """One job's scores, used by paired_bootstrap. Lists stay aligned by index."""

    score: float
    rating: float
    picks: tuple[str, ...]
    gold_docs: tuple[str, ...]
    scores: tuple[float, ...] = ()
    order_delta: float | None = None
    cost_usd: float = 0.0


@dataclass(frozen=True)
class BootstrapInterval:
    mean: float
    low: float
    high: float


def eval_fit(
    scorer: FitScorer,
    docs: Sequence[BragDoc],
    labels: Sequence[FitLabel],
    reps: int = 1,
) -> FitReport:
    """Score each label `reps` times, then once with the paragraphs reversed."""
    if reps < 1:
        raise ValueError("reps must be at least 1")
    scores: list[list[float]] = []
    picks: list[list[str]] = []
    deltas: list[float] = []
    for label in labels:
        repeated = [scorer.fit(docs, label.description) for _index in range(reps)]
        scores.append([result.score for result in repeated])
        picks.append([match.brag_doc_id for match in repeated[0].top_docs])
        reversed_score = scorer.fit(docs, reverse_order(label.description)).score
        deltas.append(abs(repeated[0].score - reversed_score))
    first = [row[0] for row in scores]
    ratings = [int(label.rating) for label in labels]
    expected = [label.docs for label in labels]
    return FitReport(
        spearman=spearman(first, [label.rating for label in labels]),
        hit_at_10=hit_at_k(picks, expected, 10),
        kappa=quadratic_kappa([score_quintile(score) for score in first], ratings),
        icc=icc(scores),
        retest_sd=retest_sd(scores),
        order_delta=(sum(deltas) / len(deltas)) if deltas else None,
        precision_at_10=precision_at_k(picks, expected, 10),
        recall_at_10=recall_at_k(picks, expected, 10),
    )


def fit_gates(report: FitReport, *, baseline_spearman: float | None) -> list[str]:
    """Empty when the scorer matches qwen3 and repeats stay within 5 points."""
    failures: list[str] = []
    if baseline_spearman is not None and (
        report.spearman is None or report.spearman < baseline_spearman
    ):
        failures.append("spearman below the qwen3 baseline")
    if report.retest_sd is None or report.retest_sd > 5:
        failures.append("retest sd above 5")
    if report.order_delta is None or report.order_delta > 5:
        failures.append("order change above 5")
    return failures


def score_quintile(score: float) -> int:
    return min(5, max(1, int(score // 20) + 1))


def objective(precision: float | None, rho: float | None) -> float | None:
    """Half precision@10 and half rank agreement, both on a 0 to 1 scale."""
    if precision is None or rho is None:
        return None
    return 0.5 * precision + 0.5 * ((rho + 1) / 2)


def paired_bootstrap(
    left: Sequence[BootstrapJob],
    right: Sequence[BootstrapJob],
    seed: int,
    resamples: int = 10_000,
) -> dict[str, BootstrapInterval]:
    """Resample the same job indexes for both versions. Returns v2 minus v1.

    `left` is v1 and `right` is v2, paired by index. The interval is the 2.5th
    to 97.5th percentile of the resampled deltas.
    """
    if len(left) != len(right) or not left:
        raise ValueError("bootstrap needs the same jobs for both versions")
    if resamples < 1:
        raise ValueError("resamples must be at least 1")
    count = len(left)
    rng = random.Random(seed)
    buckets: dict[str, list[float]] = {
        name: []
        for name in (
            "objective",
            "precision",
            "recall",
            "spearman",
            "lineup",
            "retest_sd",
            "order_delta",
            "cost",
        )
    }
    for _draw in range(resamples):
        indexes = [rng.randrange(count) for _index in range(count)]
        sample_left = [left[index] for index in indexes]
        sample_right = [right[index] for index in indexes]
        for name, delta in _bootstrap_deltas(sample_left, sample_right).items():
            if delta is not None:
                buckets[name].append(delta)
    return {name: _interval(values) for name, values in buckets.items() if values}


def _bootstrap_deltas(
    left: Sequence[BootstrapJob], right: Sequence[BootstrapJob]
) -> dict[str, float | None]:
    left_metrics = _bootstrap_metrics(left)
    right_metrics = _bootstrap_metrics(right)
    deltas: dict[str, float | None] = {}
    for name in left_metrics:
        first = left_metrics[name]
        second = right_metrics[name]
        deltas[name] = None if first is None or second is None else second - first
    return deltas


def _bootstrap_metrics(jobs: Sequence[BootstrapJob]) -> dict[str, float | None]:
    picks = [job.picks for job in jobs]
    expected = [job.gold_docs for job in jobs]
    precision = precision_at_k(picks, expected, 10)
    rho = spearman([job.score for job in jobs], [job.rating for job in jobs])
    repeats = [job.scores for job in jobs if len(job.scores) >= 2]
    order = [job.order_delta for job in jobs if job.order_delta is not None]
    return {
        "objective": objective(precision, rho),
        "precision": precision,
        "recall": recall_at_k(picks, expected, 10),
        "spearman": rho,
        "lineup": sum(len(job.picks) for job in jobs) / len(jobs),
        "retest_sd": retest_sd(repeats),
        "order_delta": (sum(order) / len(order)) if order else None,
        "cost": sum(job.cost_usd for job in jobs) / len(jobs),
    }


def _interval(values: Sequence[float]) -> BootstrapInterval:
    ordered = sorted(values)
    return BootstrapInterval(
        mean=sum(ordered) / len(ordered),
        low=_percentile(ordered, 0.025),
        high=_percentile(ordered, 0.975),
    )


def _percentile(ordered: Sequence[float], quantile: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def reverse_order(text: str) -> str:
    parts = [part for part in text.split("\n\n") if part.strip()]
    if len(parts) < 2:
        return text
    return "\n\n".join(reversed(parts))
