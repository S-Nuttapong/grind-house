"""HTML to Markdown and a stable content hash."""

import hashlib
import re

from markdownify import markdownify


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


def content_hash(title_norm: str, description_md: str | None) -> str:
    payload = f"{title_norm}\n{description_md or ''}"
    return hashlib.sha256(payload.encode()).hexdigest()
