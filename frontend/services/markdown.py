"""Sanitized Markdown rendering shared by documentation modules."""

from __future__ import annotations

import re

import bleach
import markdown
from markupsafe import Markup


_ALLOWED_TAGS = {
    "a", "blockquote", "br", "code", "del", "details", "div", "em",
    "h1", "h2", "h3", "h4", "h5", "h6", "hr", "img", "li", "ol",
    "p", "pre", "span", "strong", "summary", "table", "tbody", "td",
    "th", "thead", "tr", "ul",
}
_ALLOWED_ATTRIBUTES = {
    "a": [
        "href", "title", "target", "rel", "class",
        "data-reference-preview", "data-preview-kind", "data-preview-label",
        "data-preview-url", "data-media-url", "data-download-url",
    ],
    "code": ["class"],
    "img": ["src", "alt", "title"],
    "span": ["class"],
    "td": ["align"],
    "th": ["align"],
}
_ALLOWED_PROTOCOLS = {"http", "https", "mailto"}
_CODE_ELEMENT = re.compile(r"<(pre|code)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_DOUBLE_ESCAPED_ENTITY = re.compile(r"&amp;((?:#\d+|#x[0-9a-f]+|[a-z][a-z0-9]+));", re.IGNORECASE)


def _external_link_attributes(attrs, new=False):
    href = attrs.get((None, "href"), "")
    if href.startswith(("http://", "https://")):
        attrs[(None, "target")] = "_blank"
        attrs[(None, "rel")] = "noopener noreferrer"
    return attrs


def _restore_code_entities(rendered: str) -> str:
    """Undo linkify's extra entity layer inside already-sanitized code text."""

    return _CODE_ELEMENT.sub(
        lambda match: _DOUBLE_ESCAPED_ENTITY.sub(r"&\1;", match.group(0)),
        rendered,
    )


def render_markdown(source: str) -> Markup:
    rendered = markdown.markdown(
        source or "",
        extensions=["fenced_code", "tables", "sane_lists", "toc"],
        output_format="html5",
    )
    cleaned = bleach.clean(
        rendered,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
    )
    linked = bleach.linkify(
        cleaned,
        callbacks=[_external_link_attributes],
        skip_tags={"pre", "code"},
        parse_email=False,
    )
    return Markup(_restore_code_entities(linked))
