"""
Text-formatting helpers shared across HUD widgets.

Most HUD widgets render fixed-width tables (88-char rows) and need to clip
long values to a column width. The helpers here are intentionally tiny and
have no Rainmeter / app dependencies so they can be imported from any task
in `workflows/hud/tasks/*.py` without pulling in a heavy module graph.
"""

from __future__ import annotations


def truncate(text, width: int) -> str:
    """Trim `text` to at most `width` chars, marking overflow with '...'.

    Behaviour:
      - `None`           → ""
      - non-string       → coerced via `str()` first
      - len(text) <= width  → returned unchanged
      - width <= 3       → hard slice (no room for the ellipsis)
      - otherwise        → keep `width - 3` chars and append "..."

    Examples:
        >>> truncate("hello", 10)
        'hello'
        >>> truncate("hello world!", 11)
        'hello wo...'
        >>> truncate(None, 5)
        ''
        >>> truncate(12345, 4)
        '1...'
    """
    if text is None:
        return ""
    text = str(text)
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."
