from services.markdown import render_markdown


def test_markdown_is_sanitized_and_external_links_are_browser_safe():
    rendered = str(render_markdown(
        "# Heading\n\n[site](https://example.com)\n\n<script>alert('x')</script>"
    ))

    assert "<h1" in rendered
    assert "<script" not in rendered
    assert "alert('x')" in rendered
    assert 'target="_blank"' in rendered
    assert "noopener noreferrer" in rendered


def test_markdown_blocks_javascript_protocols():
    rendered = str(render_markdown("[bad](javascript:alert(1))"))

    assert "javascript:" not in rendered
