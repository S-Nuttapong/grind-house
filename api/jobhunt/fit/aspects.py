"""Turn a job description into the requirements the fit matrix scores against."""

import re

from jobhunt.fit.chunking import chunk_text

# Boilerplate sections are about the employer, not the work, so they are not aspects.
_BOILERPLATE = re.compile(
    r"\b(benefits?|perks?|about us|about the company|equal opportunity|eeo"
    r"|what we offer|compensation|salary|why join)\b",
    re.IGNORECASE,
)
_HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)\s*$", re.MULTILINE)
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+)$")
_MIN_BULLET = 8
_MIN_SENTENCE = 12


def split_aspects(description: str) -> list[str]:
    """Requirement bullets and sentences, with employer boilerplate sections removed.

    Falls back to paragraph chunks when the description has no usable lines.
    """
    text = description.strip()
    if not text:
        return []
    pieces: list[str] = []
    for heading, body in _sections(text):
        if heading and _BOILERPLATE.search(heading):
            continue
        pieces.extend(_pieces(body))
    if pieces:
        return pieces
    return chunk_text(text)


def _sections(text: str) -> list[tuple[str, str]]:
    matches = list(_HEADING.finditer(text))
    if not matches:
        return [("", text)]
    sections: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        sections.append(("", text[: matches[0].start()]))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append((match.group(1).strip(), text[match.end() : end]))
    return sections


def _pieces(body: str) -> list[str]:
    bullets: list[str] = []
    for line in body.splitlines():
        match = _BULLET.match(line)
        if match is None:
            continue
        bullet = match.group(1).strip()
        if len(bullet) >= _MIN_BULLET:
            bullets.append(bullet)
    if bullets:
        return bullets
    prose = " ".join(part.strip() for part in body.splitlines() if part.strip())
    if not prose:
        return []
    parts = re.split(r"(?<=[.!?])\s+", prose)
    return [part.strip() for part in parts if len(part.strip()) >= _MIN_SENTENCE]
