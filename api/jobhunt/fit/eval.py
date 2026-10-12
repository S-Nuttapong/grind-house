"""Spearman correlation and hit rate for a private fit-label file."""

import math
from collections.abc import Sequence


def spearman(left: Sequence[float], right: Sequence[float]) -> float | None:
    """Rank correlation. None when either side does not vary or there is one pair."""
    if len(left) != len(right) or len(left) < 2:
        return None
    return _pearson(_ranks(left), _ranks(right))


def hit_at_k(
    chosen: Sequence[Sequence[str]], expected: Sequence[Sequence[str]], k: int
) -> float | None:
    """Share of labeled jobs whose expected docs include one of the top k picks."""
    pairs = [(picks, wanted) for picks, wanted in zip(chosen, expected, strict=True) if wanted]
    if not pairs:
        return None
    hits = sum(1 for picks, wanted in pairs if any(doc in picks[:k] for doc in wanted))
    return hits / len(pairs)


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
