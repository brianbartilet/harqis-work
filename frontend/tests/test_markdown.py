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


def test_markdown_code_entities_render_as_text_without_double_escaping():
    rendered = str(render_markdown('```json\n{"screenshots": 0, "tag": "<safe>"}\n```'))

    assert "&amp;quot;" not in rendered
    assert "&quot;screenshots&quot;" in rendered
    assert "&lt;safe&gt;" in rendered
    assert "<safe>" not in rendered
