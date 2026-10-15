"""HTML to Markdown and a stable content hash."""

import hashlib
import re

from markdownify import markdownify


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def strip_control_chars(value: str) -> str:
    """Remove NUL and other C0 controls. Newlines and tabs stay."""
    return _CONTROL_CHARS.sub("", value)


def html_to_md(html: str) -> str:
    cleaned = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    rendered = markdownify(cleaned, strip=["script", "style"])
    rendered = re.sub(r"[ \t]+\n", "\n", rendered)
    rendered = re.sub(r"\n{3,}", "\n\n", rendered)
    return rendered.strip()


# Bump when normalization starts filling fields the old hash would have skipped.
NORMALIZE_VERSION = "facts-1"


def content_hash(title_norm: str, description_md: str | None) -> str:
    payload = f"{NORMALIZE_VERSION}\n{title_norm}\n{description_md or ''}"
    return hashlib.sha256(payload.encode()).hexdigest()
