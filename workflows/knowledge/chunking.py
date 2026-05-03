"""
Chunk-and-extract helpers shared by ingestion tasks.

Kept dependency-free (no tiktoken / spaCy) — chunk size is approximate by
character count, which is close enough for retrieval at the scales this
workflow targets. Swap this module wholesale when a real tokenizer is justified.
"""

from __future__ import annotations

from typing import Any, Iterator


_DEFAULT_CHUNK_CHARS = 2000   # ~500 tokens at 4 chars/token, matches Gemini's sweet spot
_DEFAULT_OVERLAP = 200


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
