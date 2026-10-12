"""GLiNER2 text parser. Spans still go through the default resolvers."""

from typing import Any

from jobhunt.facts.base import (
    FieldName,
    JobDetail,
    LocationFact,
    ParseHints,
    PostingInput,
    TextFact,
    as_input,
    wants,
)
from jobhunt.facts.config import gliner_thresholds
from jobhunt.facts.pay import pay_from_text, sentence_at
from jobhunt.facts.places import resolve_places

_MODEL_ID = "fastino/gliner2.5-base-v1"
_JOB_LABELS = ["fulltime", "parttime", "contract", "internship", "temporary", "unknown"]
_SNIPPET_WORDS = ("salary", "location", "hybrid", "remote")
_WORK_LABELS = ["onsite", "hybrid", "remote", "unknown"]
_loaded: dict[str, Any] = {}


class GlinerParser:
    """Local model. A span that the resolvers cannot read is dropped."""

    parser_id = "gliner"
    sends_data_offsite = False

    def __init__(
        self,
        thresholds: dict[FieldName, float] | None = None,
        model_id: str = _MODEL_ID,
    ) -> None:
        self.thresholds = thresholds or gliner_thresholds()
        self.model_id = model_id

    def parse(self, posting: PostingInput | str, hints: ParseHints | None = None) -> JobDetail:
        text = as_input(posting).description_md
        if not text.strip():
            return JobDetail()
        chosen = hints or ParseHints()
        model = load_model(self.model_id)
        detail = JobDetail()
        if wants(chosen, "pay") or wants(chosen, "locations"):
            _entities(model, text, chosen, self.thresholds, detail)
        if wants(chosen, "job_type") or wants(chosen, "workplace"):
            _classify(model, text, chosen, self.thresholds, detail)
        return detail


def load_model(model_id: str = _MODEL_ID) -> Any:
    cached = _loaded.get(model_id)
    if cached is not None:
        return cached
    from gliner2 import AutoExtractor

    model = AutoExtractor.from_pretrained(model_id)
    _loaded[model_id] = model
    return model


def _entities(
    model: Any,
    text: str,
    hints: ParseHints,
    thresholds: dict[FieldName, float],
    detail: JobDetail,
) -> None:
    labels = []
    if wants(hints, "pay"):
        labels.append("salary range")
    if wants(hints, "locations"):
        labels.append("job location")
    if not labels:
        return
    raw = model.extract_entities_long(
        text,
        labels,
        threshold=_floor(thresholds),
        chunk_size=384,
        chunk_overlap=64,
        include_spans=True,
        include_confidence=True,
    )
    entities = raw.get("entities", raw) if isinstance(raw, dict) else {}
    if wants(hints, "pay"):
        detail.pay = _pay_span(entities.get("salary range"), text, hints.country, thresholds["pay"])
    if wants(hints, "locations"):
        detail.locations = _location_spans(
            entities.get("job location"), text, thresholds["locations"]
        )


def _classify(
    model: Any,
    text: str,
    hints: ParseHints,
    thresholds: dict[FieldName, float],
    detail: JobDetail,
) -> None:
    snippet = _snippet(text)
    schema: dict[str, dict[str, object]] = {}
    if wants(hints, "job_type"):
        schema["job_type"] = {"labels": _JOB_LABELS, "cls_threshold": 0.0}
    if wants(hints, "workplace"):
        schema["workplace"] = {"labels": _WORK_LABELS, "cls_threshold": 0.0}
    raw = model.classify_text(
        snippet, schema, threshold=_floor(thresholds), include_confidence=True
    )
    if not isinstance(raw, dict):
        return
    if wants(hints, "job_type"):
        detail.job_type = _label(raw.get("job_type"), text, thresholds["job_type"], _JOB_LABELS)
    if wants(hints, "workplace"):
        detail.workplace = _label(raw.get("workplace"), text, thresholds["workplace"], _WORK_LABELS)


def _pay_span(raw: object, text: str, country: str | None, threshold: float) -> Any:
    """Resolve the sentence around each salary span. The span itself is often just the amount."""
    best: Any = None
    seen: set[str] = set()
    for item in _items(raw):
        span = str(item.get("text") or "")
        confidence = float(item.get("confidence") or 0)
        start = item.get("start")
        if confidence < threshold or not span or span not in text or not isinstance(start, int):
            continue
        sentence = sentence_at(text, start)
        if sentence in seen:
            continue
        seen.add(sentence)
        fact = pay_from_text(sentence, country, "gliner", require_cue=False)
        if fact is None or fact.evidence not in text:
            continue
        fact.confidence = confidence
        if best is None or fact.confidence > best.confidence:
            best = fact
    return best


def _location_spans(raw: object, text: str, threshold: float) -> LocationFact | None:
    places = []
    evidence = ""
    confidence = 0.0
    for item in _items(raw):
        span = str(item.get("text") or "")
        score = float(item.get("confidence") or 0)
        if score < threshold or not span or span not in text:
            continue
        found = resolve_places(span)
        if not found:
            continue
        if score > confidence:
            confidence = score
            evidence = span
        for place in found:
            if place not in places:
                places.append(place)
    if not places or evidence not in text:
        return None
    return LocationFact(value=places, confidence=confidence, evidence=evidence, parser_id="gliner")


def _label(raw: object, evidence: str, threshold: float, allowed: list[str]) -> TextFact | None:
    label, confidence = _read_label(raw)
    if label is None or label == "unknown" or label not in allowed or confidence < threshold:
        return None
    shown = evidence[:240]
    if not shown or shown not in evidence:
        return None
    return TextFact(value=label, confidence=confidence, evidence=shown, parser_id="gliner")


def _read_label(raw: object) -> tuple[str | None, float]:
    if isinstance(raw, str):
        return raw, 1.0
    if isinstance(raw, dict):
        label = raw.get("label")
        confidence = raw.get("confidence")
        if isinstance(label, str):
            return label, float(confidence) if isinstance(confidence, (int, float)) else 1.0
    return None, 0.0


def _floor(thresholds: dict[FieldName, float]) -> float:
    if not thresholds:
        return 0.0
    return min(thresholds.values())


def _items(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _snippet(text: str) -> str:
    head = text[:2500]
    extra = [
        line
        for line in text.splitlines()
        if line not in head and any(word in line.casefold() for word in _SNIPPET_WORDS)
    ]
    return head + "\n" + "\n".join(extra[:8])
