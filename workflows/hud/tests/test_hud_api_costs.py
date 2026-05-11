from datetime import datetime, timezone

import pytest

from workflows.hud.tasks.hud_api_costs import (
    _LABEL_WIDTH,
    _NO_USAGE_MESSAGE,
    _ROW_WIDTH,
    _SEP_MONTH,
    _SEP_SERVICE,
    _format_money,
    _format_row,
    _month_window,
    _render_api_costs_dump,
    _render_month_section,
    _render_service_section,
    _shorten_model_name,
    _trailing_month_windows,
    show_api_costs,
)


# ── Integration (live API; requires ANTHROPIC_ADMIN_KEY) ─────────────────────

def test__show_api_costs():
    show_api_costs(cfg_id__anthropic='ANTHROPIC', months=3, visible_lines=10)


# ── _shorten_model_name ──────────────────────────────────────────────────────

@pytest.mark.parametrize("model,expected", [
    ("claude-sonnet-4-6",         "sonnet-4-6"),
    ("claude-opus-4-7",           "opus-4-7"),
    ("claude-haiku-4-5-20251001", "haiku-4-5"),       # date suffix stripped
    ("gpt-4o",                    "4o"),
    ("gemini-1.5-pro",            "1.5-pro"),
    ("models/gemini-1.5-pro",     "gemini-1.5-pro"),  # only one prefix stripped
    ("",                          "(unknown)"),
    (None,                        "(unknown)"),
    ("a" * 30,                    "a" * 12 + "..."),  # ellipsizing fallback
])
def test__shorten_model_name(model, expected):
    assert _shorten_model_name(model) == expected


# ── _format_money / _format_row ──────────────────────────────────────────────

def test__format_money_is_8_chars_two_decimals_right_aligned():
    assert _format_money(0) == "    0.00"
    assert _format_money(127.5) == "  127.50"
    assert _format_money(16651.31) == "16651.31"
    assert len(_format_money(0)) == 8


def test__format_row_is_24_chars():
    row = _format_row("model-1", 16651.31)
    assert len(row) == _ROW_WIDTH
    assert row.startswith("model-1")
    assert row.endswith("16651.31")


def test__format_row_truncates_overlong_label_but_keeps_width():
    """A label longer than 15 chars is hard-sliced — total row width holds."""
    row = _format_row("a" * 50, 1.0)
    assert len(row) == _ROW_WIDTH


# ── _month_window / _trailing_month_windows ──────────────────────────────────

def test__month_window_april_2026_half_open():
    start, end = _month_window(2026, 4)
    assert start == "2026-04-01T00:00:00Z"
    assert end   == "2026-05-01T00:00:00Z"


def test__month_window_december_rolls_year():
    start, end = _month_window(2026, 12)
    assert start == "2026-12-01T00:00:00Z"
    assert end   == "2027-01-01T00:00:00Z"


def test__trailing_month_windows_newest_first():
    now = datetime(2026, 5, 10, tzinfo=timezone.utc)
    out = _trailing_month_windows(3, now=now)
    assert [label for _, _, label in out] == ["05-2026", "04-2026", "03-2026"]
    assert out[0][0] == 2026 and out[0][1] == 5


def test__trailing_month_windows_rolls_year_backwards():
    now = datetime(2026, 2, 1, tzinfo=timezone.utc)
    out = _trailing_month_windows(3, now=now)
    assert [label for _, _, label in out] == ["02-2026", "01-2026", "12-2025"]


# ── _render_service_section ──────────────────────────────────────────────────

def test__render_service_section_empty_returns_empty_string():
    """Zero-cost service must produce no output (filter rule)."""
    assert _render_service_section("ANTHROPIC", {}) == ""


def test__render_service_section_shape_total_and_sort():
    by_model = {"claude-sonnet-4-6": 7.51, "claude-haiku-4-5-20251001": 1.83}
    out = _render_service_section("ANTHROPIC", by_model)
    lines = out.splitlines()
    # Total row + separator + 2 model rows
    assert len(lines) == 4
    assert lines[0].startswith("ANTHROPIC")
    assert lines[0].endswith("9.34")            # 7.51 + 1.83 rounded display
    assert lines[1] == _SEP_SERVICE
    # Models sorted by cost desc.
    assert lines[2].startswith("sonnet-4-6")
    assert lines[2].endswith("7.51")
    assert lines[3].startswith("haiku-4-5")
    assert lines[3].endswith("1.83")
    # Every row is exactly _ROW_WIDTH chars.
    for line in lines:
        assert len(line) == _ROW_WIDTH


# ── _render_month_section ────────────────────────────────────────────────────

def test__render_month_section_omits_zero_cost_services():
    """OPENAI / GEMINI with empty model dicts → only ANTHROPIC renders."""
    services = [
        ("ANTHROPIC", {"claude-sonnet-4-6": 5.0}),
        ("OPENAI",    {}),
        ("GEMINI",    {}),
    ]
    out = _render_month_section("05-2026", services)
    assert "ANTHROPIC" in out
    assert "OPENAI" not in out
    assert "GEMINI" not in out
    lines = out.splitlines()
    assert lines[0].startswith("05-2026")
    assert lines[1] == _SEP_MONTH


def test__render_month_section_all_zero_shows_placeholder():
    """When every service is zero, month header + 'No usage this month'."""
    services = [("ANTHROPIC", {}), ("OPENAI", {}), ("GEMINI", {})]
    out = _render_month_section("03-2026", services)
    lines = out.splitlines()
    assert lines[0].startswith("03-2026")
    assert lines[0].endswith("0.00")
    assert lines[1] == _SEP_MONTH
    assert lines[2] == _NO_USAGE_MESSAGE
    assert len(lines) == 3                    # no service blocks rendered


def test__render_month_section_total_sums_all_services():
    services = [
        ("ANTHROPIC", {"claude-sonnet-4-6": 7.51}),
        ("OPENAI",    {"gpt-4o": 2.00}),
        ("GEMINI",    {"gemini-1.5-pro": 1.00}),
    ]
    out = _render_month_section("05-2026", services)
    # Month total = 7.51 + 2.00 + 1.00 = 10.51
    assert out.splitlines()[0].endswith("10.51")


# ── _render_api_costs_dump ───────────────────────────────────────────────────

def test__render_api_costs_dump_three_months_with_one_real_service():
    months_data = [
        ("05-2026", [("ANTHROPIC", {"claude-opus-4-7": 1.0})]),
        ("04-2026", [("ANTHROPIC", {})]),
        ("03-2026", [("ANTHROPIC", {})]),
    ]
    out = _render_api_costs_dump(months_data)
    # Three month-separator lines.
    assert out.count(_SEP_MONTH) == 3
    # Months are separated by two blank lines (== three consecutive newlines).
    assert "\n\n\n" in out
    # Empty months surface the placeholder.
    assert out.count(_NO_USAGE_MESSAGE) == 2


def test__render_api_costs_dump_empty_returns_empty_string():
    assert _render_api_costs_dump([]) == ""
