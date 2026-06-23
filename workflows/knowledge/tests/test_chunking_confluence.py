"""Confluence storage-format → plain text flattening."""

from workflows.knowledge.chunking import strip_confluence_storage, chunk_text


def test_strips_tags_and_keeps_text():
    html = "<h1>Payments</h1><p>Calls the <strong>Ledger</strong> service.</p>"
    out = strip_confluence_storage(html)
    assert "Payments" in out
    assert "Calls the Ledger service." in out
    assert "<" not in out and ">" not in out


def test_block_boundaries_become_paragraphs():
    html = "<p>First.</p><p>Second.</p>"
    out = strip_confluence_storage(html)
    assert "First." in out and "Second." in out
    # paragraphs separated by a blank line, not glued together
    assert "First.\n\nSecond." in out or "First.\nSecond." in out


def test_collapses_excess_blank_lines():
    html = "<div></div><div></div><p>Only line</p><div></div>"
    out = strip_confluence_storage(html)
    assert out.strip() == "Only line"


def test_empty_and_none_safe():
    assert strip_confluence_storage("") == ""
    assert strip_confluence_storage(None) == ""


def test_output_feeds_chunker():
    html = "<p>" + ("word " * 600) + "</p>"
    text = strip_confluence_storage(html)
    chunks = chunk_text(text)
    assert len(chunks) >= 1
    assert all(c.strip() for c in chunks)
