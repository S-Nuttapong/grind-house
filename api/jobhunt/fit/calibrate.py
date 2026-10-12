"""Turn a raw cosine similarity into a 0-100 score.

The default floor and span match BGE, whose similarities for real text cluster
between about 0.40 and 0.85. Other models pass their own constants.
"""

from collections.abc import Sequence

_RAW_FLOOR = 0.40
_RAW_SPAN = 0.45


def calibrate(raw_cosine: float, *, floor: float = _RAW_FLOOR, span: float = _RAW_SPAN) -> float:
    if span <= 0:
        return 0.0
    scaled = (raw_cosine - floor) / span * 100
    return max(0.0, min(100.0, round(scaled, 6)))


def percentile(values: Sequence[float], fraction: float) -> float:
    """Linear-interpolation percentile. `fraction` is between 0 and 1."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile of an empty sequence")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def suggest_floor_span(raw_scores: Sequence[float]) -> tuple[float, float] | None:
    """Floor and span that stretch the 5th–95th percentile of raw scores to 0–100."""
    if len(raw_scores) < 2:
        return None
    floor = percentile(raw_scores, 0.05)
    ceiling = percentile(raw_scores, 0.95)
    span = ceiling - floor
    if span <= 0:
        return None
    return floor, span


def tier(score: float) -> str:
    if score >= 80:
        return "strong"
    if score >= 60:
        return "good"
    if score >= 40:
        return "fair"
    return "low"
