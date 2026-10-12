"""Job title normalization."""

import re

_EXPANSIONS = (
    (r"\bsr\b", "senior"),
    (r"\bjr\b", "junior"),
    (r"\bswe\b", "software engineer"),
    (r"\beng\b", "engineer"),
    (r"\bdev\b", "developer"),
)

_PHRASES = (
    (r"front[\s-]?end", "frontend"),
    (r"back[\s-]?end", "backend"),
    (r"full[\s-]?stack", "fullstack"),
)

_TRAILING = re.compile(
    r"""
    (?:
        \s*[\(\[][^)\]]*[\)\]]
        |
        \s*[-|,/]\s*(?:remote|hybrid|onsite|work\s+from\s+home|wfh|anywhere
            |singapore|bangkok|thailand|usa|us|uk|london|new\s+york)
    )$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def norm_title(title: str) -> str:
    text = title.lower().strip()
    for pattern, replacement in _PHRASES:
        text = re.sub(pattern, replacement, text)
    while True:
        stripped = _TRAILING.sub("", text).strip()
        if stripped == text:
            break
        text = stripped
    for pattern, replacement in _EXPANSIONS:
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()
