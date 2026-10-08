"""Split long texts into pieces the embedding model can read whole.

BGE truncates at 512 tokens, and the brag docs are far longer than that, so the
profile goes in as one chunk per entry and each job description is cut into
chunks of roughly 400 tokens.
"""

_CHARS_PER_TOKEN = 4
CHUNK_CHARS = 400 * _CHARS_PER_TOKEN


def chunk_text(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Split on paragraph boundaries, keeping each piece near `size` characters."""
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    if not paragraphs:
        return [text.strip()] if text.strip() else []
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 2 > size:
            chunks.append(current)
            current = ""
        while len(paragraph) > size:
            chunks.append(paragraph[:size])
            paragraph = paragraph[size:]
        current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)
    return chunks
