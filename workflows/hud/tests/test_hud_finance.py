from datetime import date

import pytest

from workflows.hud.tasks.hud_finance import (
    _group_by_month,
    _render_pc_daily_sales_dump,
    _sum_amount_by_day,
    show_pc_daily_sales,
    show_ynab_budgets_info,
)


def test__show_ynab_budgets_info():
    show_ynab_budgets_info(cfg_id__ynab='YNAB', cfg_id__calendar="GOOGLE_APPS")


def test__show_pc_daily_sales():
    show_pc_daily_sales(cfg_id__appsheet='APPSHEET', days=60, visible_lines=10)


@pytest.mark.parametrize("rows,expected", [
    # Two rows on the same day → summed.
    (
        [{"DATE": "06/22/2024", "TOTAL PRICE": "127"},
         {"DATE": "06/22/2024", "TOTAL PRICE": "100"}],
        {date(2024, 6, 22): 227.0},
    ),
    # Different days → separate buckets.
    (
        [{"DATE": "06/22/2024", "TOTAL PRICE": "10"},
         {"DATE": "06/23/2024", "TOTAL PRICE": "20"}],
        {date(2024, 6, 22): 10.0, date(2024, 6, 23): 20.0},
    ),
    # Empty input → empty dict.
    ([], {}),
])
def test__sum_amount_by_day_basic(rows, expected):
    assert _sum_amount_by_day(rows) == expected


def test__sum_amount_by_day_skips_invalid_rows():
    rows = [
        {"DATE": "06/22/2024", "TOTAL PRICE": "127"},   # ok
        {"DATE": "",            "TOTAL PRICE": "50"},   # blank date
        {"DATE": "06/22/2024", "TOTAL PRICE": ""},      # blank amount
        {"DATE": "not-a-date", "TOTAL PRICE": "10"},    # unparseable date
        {"DATE": "06/22/2024", "TOTAL PRICE": "abc"},   # unparseable amount
        {"DATE": None,         "TOTAL PRICE": "1"},     # None date
    ]
    assert _sum_amount_by_day(rows) == {date(2024, 6, 22): 127.0}


def test__sum_amount_by_day_honours_custom_field_names():
    rows = [{"d": "01/02/2025", "x": "5"}, {"d": "01/02/2025", "x": "7.5"}]
    assert _sum_amount_by_day(rows, amount_field="x", date_field="d") == {
        date(2025, 1, 2): 12.5,
    }


def test__group_by_month_orders_months_recent_first():
    daily = {
        date(2026, 4, 30): 10.0,
        date(2026, 5, 1): 20.0,
        date(2026, 5, 2): 30.0,
        date(2026, 3, 15): 5.0,
    }
    groups = _group_by_month(daily)
    assert [label for label, _ in groups] == ["MAY", "APRIL", "MARCH"]
    # Days within a month must be descending.
    may_days = [d for d, _ in groups[0][1]]
    assert may_days == [date(2026, 5, 2), date(2026, 5, 1)]


def test__render_pc_daily_sales_dump_has_month_header_and_separator():
    daily = {
        date(2026, 5, 2): 17000.50,
        date(2026, 5, 1): 7000.00,
        date(2026, 4, 30): 217000.09,
    }
    out = _render_pc_daily_sales_dump(daily)
    lines = out.splitlines()
    assert lines[0] == "MAY"
    assert lines[1] == "-" * 24
    # 24-char rows: date(10) + 5 spaces + width-9 right-aligned amount.
    assert lines[2] == "02-05-2026      17000.50"
    assert lines[3] == "01-05-2026       7000.00"
    assert lines[4] == ""                                     # blank between months
    assert lines[5] == "APRIL"
    assert lines[6] == "-" * 24
    assert lines[7] == "30-04-2026     217000.09"
    for line in (lines[2], lines[3], lines[7]):
        assert len(line) == 24


def test__render_pc_daily_sales_dump_empty_input_returns_empty_string():
    assert _render_pc_daily_sales_dump({}) == ""