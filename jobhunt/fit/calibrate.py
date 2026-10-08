"""Turn a raw cosine similarity into a 0-100 score.

BGE cosine similarities for real text cluster between about 0.40 and 0.85,
so that span is stretched to the full range.
"""

_RAW_FLOOR = 0.40
_RAW_SPAN = 0.45


def calibrate(raw_cosine: float) -> float:
    scaled = (raw_cosine - _RAW_FLOOR) / _RAW_SPAN * 100
    return max(0.0, min(100.0, scaled))


def tier(score: float) -> str:
    if score >= 80:
        return "strong"
    if score >= 60:
        return "good"
    if score >= 40:
        return "fair"
    return "low"
