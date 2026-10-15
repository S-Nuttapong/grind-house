"""Years of experience stated in a title or description."""

import re

from jobhunt.facts.base import Experience, ExperienceFact
from jobhunt.facts.lexicon import cues
from jobhunt.facts.pay import sentence_at

_YEAR_WORD = r"years?|yrs?|year['’]s"
_GAP = r"[ \t]{0,3}"
_EXPERIENCE = re.compile(
    rf"(?P<low>\d{{1,2}})"
    rf"(?:"
    rf"(?P<plus>{_GAP}(?:\\?\+|plus\b))"
    rf"|"
    rf"(?:{_GAP}(?:\\?-|–|—|\bto\b){_GAP}(?P<high>\d{{1,2}}){_GAP}(?:\\?\+|plus\b)?)"
    rf")?"
    rf"{_GAP}(?:{_YEAR_WORD})\b",
    re.IGNORECASE,
)
_MAX_YEARS = 20


def experience_from_text(text: str, parser_id: str = "default") -> ExperienceFact | None:
    """The first requirement that is clearly about the candidate's experience."""
    for match in _EXPERIENCE.finditer(text):
        low = int(match.group("low"))
        high_raw = match.group("high")
        high = int(high_raw) if high_raw is not None else None
        if match.group("plus"):
            high = None
        if high is not None and high < low:
            continue
        if low > _MAX_YEARS or (high is not None and high > _MAX_YEARS):
            continue
        sentence = sentence_at(text, match.start())
        if not _cue(sentence) or _rejected(sentence):
            continue
        evidence = text[match.start() : match.end()]
        return ExperienceFact(
            value=Experience(minimum=low, maximum=high),
            confidence=1.0,
            evidence=evidence,
            parser_id=parser_id,
        )
    return None


def _cue(sentence: str) -> bool:
    folded = sentence.casefold()
    for cue in cues("experience_cues"):
        if " " in cue:
            if cue in folded:
                return True
            continue
        if cue == "experience" and re.search(r"\bexperiences?\b", folded):
            return True
        if re.search(rf"\b{re.escape(cue)}\b", folded):
            return True
    return False


def _rejected(sentence: str) -> bool:
    folded = sentence.casefold()
    return any(re.search(rf"\b{re.escape(word)}\b", folded) for word in cues("experience_reject"))
