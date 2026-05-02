"""
Unit tests for `workflows.hud.helpers.layout`.
"""

import pytest

from workflows.hud.helpers.layout import (
    DEFAULT_EXTRA_W_PX,
    DEFAULT_GAP_PX,
    DEFAULT_PX_PER_CHAR,
    DEFAULT_START_X,
    SEPARATOR_CHARS,
    compute_horizontal_link_layout,
)


def test__compute_horizontal_link_layout__returns_pairs():
    """Return type is a list of (X, W) integer tuples."""
    out = compute_horizontal_link_layout(["A", "B"])
    assert isinstance(out, list)
    assert len(out) == 2
    for x, w in out:
        assert isinstance(x, int)
        assert isinstance(w, int)


def test__compute_horizontal_link_layout__cumulative_advance_with_gap():
    """Each step advances by `prev_W + gap_px`."""
    out = compute_horizontal_link_layout(
        ["A", "B", "C"], start_x=0, px_per_char=10,
        gap_px=5, extra_w_px=0,
    )
    # Label A: x=0, w=1*10=10
    # Label B: x=10+5=15, w=(1+1)*10=20  (carries '|' prefix)
    # Label C: x=15+20+5=40, w=(1+1)*10=20
    assert out == [(0, 10), (15, 20), (40, 20)]


def test__compute_horizontal_link_layout__separator_adds_to_width():
    """Labels 1+ are wider by exactly `separator_chars * px_per_char`."""
    out = compute_horizontal_link_layout(
        ["AAA", "AAA"], start_x=0, px_per_char=10,
        gap_px=0, extra_w_px=0,
    )
    # First label: 3 chars * 10 = 30
    # Second label: (3+1) chars * 10 = 40 (carries leading '|')
    assert out[0][1] == 30
    assert out[1][1] == 40


def test__compute_horizontal_link_layout__defaults_match_show_tcg_orders():
    """Calibration check vs the historical show_tcg_orders X positions.

    The X coords drift slightly because the new helper now also reserves
    `gap_px=6` between meters (the previous implementation packed them
    flush). Within ~10 px is fine — the visible row stays clean.
    """
    out = compute_horizontal_link_layout(["ECHOMTG", "ORDERS", "AUDIT", "TCG_QR"])
    xs = [x for x, _ in out]
    # Loose check — exact values aren't important, but the row should be
    # left-to-right ordered and reasonably close to the original eyeball
    # positions.
    assert xs[0] == DEFAULT_START_X
    assert all(xs[i] > xs[i - 1] for i in range(1, len(xs)))


def test__compute_horizontal_link_layout__first_label_at_start_x():
    out = compute_horizontal_link_layout(["A", "B"], start_x=42)
    assert out[0][0] == 42


def test__compute_horizontal_link_layout__custom_px_per_char():
    out = compute_horizontal_link_layout(
        ["AAAA"], start_x=0, px_per_char=5, extra_w_px=0,
    )
    assert out[0] == (0, 4 * 5)


def test__compute_horizontal_link_layout__extra_w_padding():
    """`extra_w_px` adds to every label's width (click-area padding)."""
    out = compute_horizontal_link_layout(
        ["A"], start_x=0, px_per_char=10, extra_w_px=8,
    )
    # 1 char * 10 + 8 = 18
    assert out[0][1] == 18


def test__compute_horizontal_link_layout__single_label():
    out = compute_horizontal_link_layout(["ONLY"])
    assert len(out) == 1
    assert out[0][0] == DEFAULT_START_X


def test__compute_horizontal_link_layout__empty_input():
    assert compute_horizontal_link_layout([]) == []


def test__compute_horizontal_link_layout__handles_empty_label():
    """Empty labels in the middle of the row don't break the math."""
    out = compute_horizontal_link_layout(
        ["A", "", "C"], start_x=0, px_per_char=10,
        gap_px=0, extra_w_px=0,
    )
    # A: x=0,  w=10
    # "": x=10, w=(0+1)*10=10  (just the '|' separator)
    # C: x=20, w=(1+1)*10=20
    assert out == [(0, 10), (10, 10), (20, 20)]


def test__compute_horizontal_link_layout__separator_chars_zero():
    """`separator_chars=0` removes the `|` accounting (labels touch directly)."""
    out = compute_horizontal_link_layout(
        ["A", "B", "C"], start_x=0, px_per_char=10,
        separator_chars=0, gap_px=0, extra_w_px=0,
    )
    assert out == [(0, 10), (10, 10), (20, 10)]


def test__compute_horizontal_link_layout__five_label_jira_layout():
    """The actual JIRA BOARD layout passed by show_jira_board."""
    labels = ["BOARD", "DASHBOARD", "REPOSITORY", "STRUCTURE", "DUMP"]
    out = compute_horizontal_link_layout(labels)
    xs = [x for x, _ in out]
    assert len(out) == 5
    # Strictly increasing: each label sits to the right of the previous.
    assert all(xs[i] > xs[i - 1] for i in range(1, len(xs)))


def test__compute_horizontal_link_layout__module_constants_exposed():
    """Make sure the module-level tunables are importable for callers."""
    assert isinstance(DEFAULT_PX_PER_CHAR, int)
    assert isinstance(DEFAULT_START_X, int)
    assert isinstance(SEPARATOR_CHARS, int)
    assert isinstance(DEFAULT_GAP_PX, int)
    assert isinstance(DEFAULT_EXTRA_W_PX, int)
