"""Pick a parser chain per field from bake-off numbers. Precision wins over recall."""

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from jobhunt.core.paths import config_path
from jobhunt.facts.base import FIELDS
from jobhunt.facts.config import reload_config


@dataclass(frozen=True)
class ModeScore:
    mode: str
    precision: float | None
    recall: float | None
    p50_seconds: float


@dataclass(frozen=True)
class FieldChoice:
    field: str
    mode: str
    flagged: bool
    reason: str


def choose_field(scores: list[ModeScore]) -> FieldChoice:
    """Discard anything under 0.97 precision, then take the highest recall.

    Within one recall point, the faster mode wins. If nothing reaches 0.97,
    keep the most precise mode that still reaches 0.90 and flag it. Below
    that, the field stays on source data only.
    """
    usable = [score for score in scores if _at_least(score.precision, 0.97)]
    if usable:
        winner = _best(usable)
        return FieldChoice(field="", mode=winner.mode, flagged=False, reason="precision>=0.97")
    fallback = [score for score in scores if _at_least(score.precision, 0.90)]
    if not fallback:
        return FieldChoice(field="", mode="api", flagged=False, reason="none reached 0.90")
    winner = max(fallback, key=lambda score: score.precision or 0)
    return FieldChoice(field="", mode=winner.mode, flagged=True, reason="precision>=0.90")


def write_config(report_path: Path) -> Path:
    """Write facts.yaml from a bench JSON file. The report is the input, not a guess."""
    payload = json.loads(report_path.read_text())
    choices = payload.get("choices")
    thresholds = payload.get("thresholds")
    if not isinstance(choices, dict) or not isinstance(thresholds, dict):
        raise ValueError(f"{report_path} is missing choices or thresholds")
    chains: dict[str, list[str]] = {}
    flagged: list[str] = []
    for field in FIELDS:
        if field == "posted":
            chains[field] = ["api"]
            continue
        choice = choices.get(field)
        if not isinstance(choice, dict):
            chains[field] = ["api"]
            continue
        mode = str(choice.get("mode") or "api")
        chains[field] = chain_for(mode)
        if choice.get("flagged") is True:
            flagged.append(field)
    document = {
        "chains": chains,
        "gliner": {
            field: float(thresholds.get(field, 0.5)) for field in FIELDS if field != "posted"
        },
        "flagged": flagged,
    }
    path = config_path("facts.yaml")
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    reload_config()
    return path


def chain_for(mode: str) -> list[str]:
    if mode == "default":
        return ["api", "default"]
    if mode == "gliner":
        return ["api", "gliner"]
    if mode == "default+gliner":
        return ["api", "default", "gliner"]
    return ["api"]


def _best(scores: list[ModeScore]) -> ModeScore:
    ranked = sorted(scores, key=lambda score: score.recall or 0, reverse=True)
    leader = ranked[0]
    close = [score for score in ranked if (leader.recall or 0) - (score.recall or 0) <= 0.01]
    return min(close, key=lambda score: score.p50_seconds)


def _at_least(value: float | None, bar: float) -> bool:
    return value is not None and value >= bar
