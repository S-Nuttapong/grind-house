"""Render job descriptions. Raw HTML in the source is escaped, not executed."""

from markdown_it import MarkdownIt
from markupsafe import Markup

_markdown = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})


def render_markdown(value: object) -> Markup:
    if not value:
        return Markup("")
    return Markup(_markdown.render(str(value)))
