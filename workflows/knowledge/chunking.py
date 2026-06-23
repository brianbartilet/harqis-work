"""
Chunk-and-extract helpers shared by ingestion tasks.

Kept dependency-free (no tiktoken / spaCy) — chunk size is approximate by
character count, which is close enough for retrieval at the scales this
workflow targets. Swap this module wholesale when a real tokenizer is justified.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any, Iterator


_DEFAULT_CHUNK_CHARS = 2000   # ~500 tokens at 4 chars/token, matches Gemini's sweet spot
_DEFAULT_OVERLAP = 200

# Confluence storage-format block tags — emit a paragraph break after each so
# the downstream chunker stays paragraph-aware.
_CONFLUENCE_BLOCK_TAGS = {
    "p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "table", "ac:structured-macro", "ac:layout-cell", "ac:layout-section",
}


def chunk_text(
    text: str,
    chunk_chars: int = _DEFAULT_CHUNK_CHARS,
    overlap: int = _DEFAULT_OVERLAP,
) -> list[str]:
    """Greedy fixed-size chunker with overlap.

    Splits on paragraph boundaries when possible to avoid mid-sentence cuts.
    Falls back to hard slicing for runs of text without blank lines.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_chars:
        return [text]

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        candidate = (buf + "\n\n" + para).strip() if buf else para
        if len(candidate) <= chunk_chars:
            buf = candidate
            continue
        if buf:
            chunks.append(buf)
            tail = buf[-overlap:] if overlap > 0 else ""
            buf = (tail + "\n\n" + para).strip()
        else:
            for i in range(0, len(para), chunk_chars - overlap):
                chunks.append(para[i : i + chunk_chars])
            buf = ""
    if buf:
        chunks.append(buf)
    return chunks


def extract_notion_block_text(block: dict[str, Any]) -> str:
    """Pull plain text out of a Notion block — covers the common block types.

    Notion's API returns rich text under different keys per block type. We
    handle the ones that appear in narrative pages; structural blocks (column
    layouts, embeds, etc.) drop through and contribute no text, which is fine
    for retrieval.
    """
    btype = block.get("type")
    if not btype:
        return ""
    body = block.get(btype) or {}

    rich = body.get("rich_text")
    if isinstance(rich, list):
        return "".join(r.get("plain_text", "") for r in rich)

    if btype == "child_page":
        return body.get("title", "")

    return ""


class _ConfluenceStorageStripper(HTMLParser):
    """Flatten Confluence storage-format XHTML to plain text.

    Storage format is XHTML plus Atlassian macros (``<ac:...>``,
    ``<ri:...>``). We keep visible text and CDATA payloads (code blocks live in
    ``<ac:plain-text-body><![CDATA[...]]></ac:plain-text-body>``), insert
    paragraph breaks at block boundaries, and drop everything else. No external
    HTML library — the stdlib parser is enough for retrieval-grade text.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _CONFLUENCE_BLOCK_TAGS:
            self._parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag in _CONFLUENCE_BLOCK_TAGS:
            self._parts.append("\n\n")

    def handle_data(self, data):
        if data:
            self._parts.append(data)

    # CDATA inside <ac:plain-text-body> arrives via handle_data when
    # convert_charrefs is on, but unknown declarations (the raw CDATA marker)
    # come through here on some Python builds — capture them too.
    def unknown_decl(self, data):
        if data.startswith("CDATA["):
            self._parts.append(data[6:])

    def text(self) -> str:
        return "".join(self._parts)


def strip_confluence_storage(storage_html: str) -> str:
    """Convert a Confluence page's storage-format body to plain text.

    Collapses runs of blank lines so the paragraph-aware chunker doesn't see
    dozens of empty paragraphs from nested macro markup. Robust to None/empty.
    """
    if not storage_html:
        return ""
    parser = _ConfluenceStorageStripper()
    try:
        parser.feed(storage_html)
    except Exception:  # noqa: BLE001 — malformed markup shouldn't kill an ingest
        pass
    raw = parser.text()
    # Normalise whitespace: trim each line, drop empties, rejoin paragraphs.
    lines = [ln.strip() for ln in raw.splitlines()]
    out: list[str] = []
    blank = False
    for ln in lines:
        if ln:
            out.append(ln)
            blank = False
        elif not blank and out:
            out.append("")  # single paragraph separator
            blank = True
    return "\n".join(out).strip()


def flatten_adf(node: Any) -> str:
    """Flatten an Atlassian Document Format (ADF) tree to plain text.

    Jira Cloud REST v3 returns issue descriptions and comments as ADF JSON —
    a recursive node tree with `type`, `content`, and (for leaf text nodes)
    `text` keys. We walk the tree depth-first and concatenate every `text`
    field. Block-level boundaries become double newlines so chunking stays
    paragraph-aware.

    Robust to: plain strings (returned unchanged), empty/None inputs (return
    ""), and unrecognised node types (recursed into anyway).
    """
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""

    out: list[str] = []
    if "text" in node and isinstance(node["text"], str):
        out.append(node["text"])

    for child in node.get("content", []) or []:
        out.append(flatten_adf(child))

    block_types = {"paragraph", "heading", "bulletList", "orderedList",
                   "listItem", "blockquote", "codeBlock", "panel"}
    sep = "\n\n" if node.get("type") in block_types else ""
    return sep + "".join(out) + sep


def iter_notion_blocks(
    page_id: str,
    blocks_service: Any,
    *,
    max_pages: int = 10,
) -> Iterator[dict[str, Any]]:
    """Yield every block under a Notion page, paginating through children.

    `blocks_service` is an `ApiServiceNotionBlocks` instance. We don't recurse
    into nested children here — adequate for flat note-style pages and keeps
    the worker bounded. Promote to recursive when a real corpus needs it.
    """
    cursor = None
    pages_seen = 0
    while pages_seen < max_pages:
        resp = blocks_service.get_block_children(
            block_id=page_id, start_cursor=cursor, page_size=100
        )
        if not isinstance(resp, dict):
            return
        for block in resp.get("results", []):
            yield block
        if not resp.get("has_more"):
            return
        cursor = resp.get("next_cursor")
        if not cursor:
            return
        pages_seen += 1
