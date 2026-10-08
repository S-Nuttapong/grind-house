"""Company name normalization."""

import re
import unicodedata

_SUFFIXES = (
    "(thailand)",
    "(singapore)",
    "sdn bhd",
    "pte ltd",
    "corporation",
    "limited",
    "gmbh",
    "corp",
    "inc",
    "llc",
    "ltd",
    "pte",
    "plc",
    "co",
    "bv",
    "sa",
    "ag",
)


def norm_company(name: str) -> str:
    text = unicodedata.normalize("NFKD", name)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower()
    text = re.sub(r"[^\w\s()]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    changed = True
    while changed:
        changed = False
        for suffix in _SUFFIXES:
            if text == suffix:
                break
            if text.endswith(" " + suffix):
                text = text[: -(len(suffix) + 1)].strip()
                changed = True
                break
    return re.sub(r"\s+", " ", text).strip()
