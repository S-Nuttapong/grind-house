"""Default parser. Libraries do the parsing; this module decides where to look."""

import re

from markdown_it import MarkdownIt

from jobhunt.facts.base import (
    JobDetail,
    LocationFact,
    ParseHints,
    TextFact,
    wants,
)
from jobhunt.facts.lexicon import cues, phrases
from jobhunt.facts.pay import pay_from_text
from jobhunt.facts.places import resolve_places

_FENCE = MarkdownIt()
_WORKPLACE = {
    "hybrid": "hybrid",
    "remote": "remote",
    "on-site": "onsite",
    "onsite": "onsite",
    "in-office": "onsite",
}
_TYPE_LINE = re.compile(
    r"^(full-time|full time|part-time|part time|contract|internship|intern|temporary)\b",
    re.IGNORECASE,
)


class DefaultParser:
    """Rules over the description. High precision: a guess is left unknown."""

    parser_id = "default"
    sends_data_offsite = False

    def parse(self, text: str, hints: ParseHints | None = None) -> JobDetail:
        if not text.strip():
            return JobDetail()
        chosen = hints or ParseHints()
        body = _blank_fences(text)
        detail = JobDetail()
        if wants(chosen, "pay"):
            detail.pay = pay_from_text(body, chosen.country, self.parser_id)
        if wants(chosen, "locations"):
            detail.locations = _locations(body)
        if wants(chosen, "job_type"):
            detail.job_type = _job_type(body)
        if wants(chosen, "workplace"):
            detail.workplace = _workplace(body)
        return detail


def _blank_fences(text: str) -> str:
    """Drop fenced code so a sample paycheck or address is not a fact."""
    skip: set[int] = set()
    for token in _FENCE.parse(text):
        if token.type == "fence" and token.map is not None:
            start, end = token.map
            skip.update(range(start, end))
    if not skip:
        return text
    lines = text.splitlines(keepends=True)
    return "".join(" " * len(line) if index in skip else line for index, line in enumerate(lines))


def _locations(text: str) -> LocationFact | None:
    chunks: list[str] = []
    for line in text.splitlines():
        folded = line.casefold()
        if ":" not in line or not any(cue in folded for cue in cues("location_cues")):
            continue
        chunks.append(line.split(":", 1)[1])
    if not chunks and len(text) <= 80 and "\n" not in text:
        chunks.append(text)
    places = []
    evidence: list[str] = []
    for chunk in chunks:
        found = resolve_places(chunk)
        if not found:
            continue
        evidence.append(chunk.strip())
        for place in found:
            if place not in places:
                places.append(place)
    if not places or not evidence:
        return None
    shown = evidence[0]
    if shown not in text:
        return None
    return LocationFact(value=places, confidence=1.0, evidence=shown, parser_id="default")


def _job_type(text: str) -> TextFact | None:
    found: list[tuple[str, str]] = []
    table = phrases("job_type")
    for line in _lines(text):
        if not _is_type_line(line):
            continue
        folded = line.casefold()
        for label, words in table.items():
            for word in words:
                if re.search(rf"\b{re.escape(word)}\b", folded):
                    found.append((label, line.strip()))
        compact = re.sub(r"[^a-z0-9]+", "", folded)
        for label, token in _multilingual_types():
            if token in compact:
                found.append((label, line.strip()))
    labels = {label for label, _evidence in found}
    if len(labels) != 1:
        return None
    label, evidence = found[0]
    if evidence not in text:
        return None
    return TextFact(value=label, confidence=1.0, evidence=evidence, parser_id="default")


def _workplace(text: str) -> TextFact | None:
    order = ("hybrid", "onsite", "remote")
    table = phrases("workplace")
    for line in _lines(text):
        folded = line.casefold().strip()
        paren = re.search(r"\((hybrid|remote|on-?site|onsite|in-office)\)", folded)
        if paren:
            label = _WORKPLACE.get(paren.group(1), "")
            if label and line.strip() in text:
                return _text(label, line)
        leading = re.match(r"(remote|hybrid|on-?site|onsite|in-office)\b", folded)
        if leading and line.strip() in text:
            label = _WORKPLACE.get(leading.group(1), "")
            if label:
                return _text(label, line)
        if not any(cue in folded for cue in cues("workplace_cues")):
            continue
        for label in order:
            for word in table.get(label, []):
                if re.search(rf"\b{re.escape(word)}\b", folded) and line.strip() in text:
                    return _text(label, line)
    return None


def _text(label: str, line: str) -> TextFact:
    return TextFact(value=label, confidence=1.0, evidence=line.strip(), parser_id="default")


def _is_type_line(line: str) -> bool:
    folded = line.casefold()
    if any(cue in folded for cue in cues("type_cues")):
        return True
    return _TYPE_LINE.match(folded.strip()) is not None


def _lines(text: str) -> list[str]:
    rows = text.splitlines()
    return rows if rows else [text]


def _multilingual_types() -> list[tuple[str, str]]:
    from jobspy.model import JobType

    mapping = {
        JobType.FULL_TIME: "fulltime",
        JobType.PART_TIME: "parttime",
        JobType.CONTRACT: "contract",
        JobType.TEMPORARY: "temporary",
        JobType.INTERNSHIP: "internship",
    }
    found: list[tuple[str, str]] = []
    for kind, label in mapping.items():
        for token in kind.value:
            if len(token) >= 8:
                found.append((label, token.casefold()))
    return found
