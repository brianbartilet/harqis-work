"""
Unit tests for `workflows.hud.helpers.sizing`.
"""

from workflows.hud.helpers.sizing import (
    DEFAULT_MAX_HUD_LINES,
    HUD_LINE_BUFFER,
    compute_max_hud_lines,
)


def test__compute_max_hud_lines__uses_dump_line_count_plus_buffer():
    dump = "line1\nline2\nline3"   # 3 lines, fits under default cap
    assert compute_max_hud_lines(dump) == 3 + HUD_LINE_BUFFER


def test__compute_max_hud_lines__caps_at_default():
    """Long dump caps at the default ceiling — overflow is meant to scroll."""
    dump = "\n" * (DEFAULT_MAX_HUD_LINES * 4)   # huge dump
    assert compute_max_hud_lines(dump) == DEFAULT_MAX_HUD_LINES


def test__compute_max_hud_lines__custom_cap_smaller():
    """A tighter cap forces scrolling sooner — useful for very compact widgets."""
    dump = "\n" * 100
    assert compute_max_hud_lines(dump, cap=8) == 8


def test__compute_max_hud_lines__custom_cap_larger():
    """A larger cap allows the widget to grow until that ceiling."""
    dump = "\n" * 50
    assert compute_max_hud_lines(dump, cap=40) == 40


def test__compute_max_hud_lines__empty_dump_returns_buffer_only():
    assert compute_max_hud_lines("") == HUD_LINE_BUFFER


def test__compute_max_hud_lines__single_line_dump():
    """One line, no trailing newline."""
    assert compute_max_hud_lines("hello") == 1 + HUD_LINE_BUFFER


def test__compute_max_hud_lines__counts_trailing_newline():
    """Trailing newline => N \\n + the empty final 'line'."""
    dump = "a\nb\n"   # 3 'lines' by the counter (a, b, '')
    assert compute_max_hud_lines(dump) == 3 + HUD_LINE_BUFFER


def test__compute_max_hud_lines__cap_smaller_than_buffer_short_dump():
    """If the dump fits under the (very small) cap, the cap is the ceiling."""
    dump = "x"
    assert compute_max_hud_lines(dump, cap=1) == 1
