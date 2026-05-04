from collections import defaultdict
from datetime import date, datetime

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.data.strings import make_separator
from core.utilities.logging.custom_logger import logger as log

from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_meter
from apps.desktop.helpers.feed import feed

from apps.ynab.references.web.api.budgets import ApiServiceYNABBudgets
from apps.ynab.config import APP_NAME as APP_NAME_YNAB
from apps.ynab.references.constants import YNAB_MILLIUNITS

from apps.appsheet.references.web.api.tables import ApiServiceAppSheetTables
from apps.appsheet.config import APP_NAME as APP_NAME_APPSHEET

from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.apps_config import CONFIG_MANAGER

from apps.google_apps.references.constants import ScheduleCategory

from workflows.hud.helpers.sizing import compute_max_hud_lines
from workflows.hud.tasks.sections import sections__ynab, sections__pc_daily_sales


@SPROUT.task()
@log_result()
@init_meter(RAINMETER_CONFIG, hud_item_name='BUDGETING INFO', new_sections_dict=sections__ynab, play_sound=True,
            schedule_categories=[ScheduleCategory.FINANCE, ])
@feed()
def show_ynab_budgets_info(ini=ConfigHelperRainmeter(), **kwargs):
    log.info("Showing available keyword arguments: {0}".format(str(kwargs.keys())))
    budget_percent_warning = kwargs.get('budget_percent_warning', 20 / 100)

    # region Fetch YNAB data
    cfg_id__ynab = kwargs.get('cfg_id__ynab', APP_NAME_YNAB)
    cfg__ynab = CONFIG_MANAGER.get(cfg_id__ynab)

    service = ApiServiceYNABBudgets(cfg__ynab)
    budget_id_sgd = cfg__ynab.app_data['budget_sgd_id']
    budget_id_php = cfg__ynab.app_data['budget_php_id']

    # SGD main budgeting account
    category_groups = service.get_categories(budget_id_sgd)

    # get overbudgeted categories, remaining and current

    categories_fetched = []
    for category_group in category_groups['category_groups']:
        for category in category_group['categories']:
            category_name = category['name']
            budgeted = category['budgeted'] / YNAB_MILLIUNITS
            budgeted_warning = budgeted * budget_percent_warning
            balance = category['balance'] / YNAB_MILLIUNITS
            if balance <= budgeted_warning and budgeted > 0:
                categories_fetched.append((category_name, budgeted_warning, budgeted, balance))

    # endregion

    # region Build links

    url_budget_sgd = f'https://app.ynab.com/{budget_id_sgd}/budget'
    ini['meterLink']['text'] = "SGD"
    ini['meterLink']['leftmouseupaction'] = '!Execute ["{0}" 3]'.format(url_budget_sgd)
    ini['meterLink']['tooltiptext'] = url_budget_sgd

    url_budget_php = f'https://app.ynab.com/{budget_id_php}/budget'
    ini['meterLink_php']['Meter'] = 'String'
    ini['meterLink_php']['MeterStyle'] = 'sItemLink'
    ini['meterLink_php']['X'] = '(28*#Scale#)'
    ini['meterLink_php']['Y'] = '(38*#Scale#)'
    ini['meterLink_php']['W'] = '60'
    ini['meterLink_php']['H'] = '55'
    ini['meterLink_php']['Text'] = '|PHP'
    ini['meterLink_php']['LeftMouseUpAction'] = '!Execute["{0}" 3]'.format(url_budget_php)
    ini['meterLink_php']['tooltiptext'] = url_budget_php

    # endregion

    # region Set dimensions
    width_multiplier = 1.5
    ini['meterSeperator']['W'] = '({0}*186*#Scale#)'.format(width_multiplier)

    ini['MeterDisplay']['W'] = '({0}*186*#Scale#)'.format(width_multiplier)
    ini['MeterDisplay']['H'] = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'
    ini['MeterDisplay']['X'] = '14'
    ini['MeterBackground']['Shape'] = ('Rectangle 0,0,({0}*190),(36+(#ItemLines#*22)),2 | Fill Color #fillColor# '
                                       '| StrokeWidth (1*#Scale#) | Stroke Color [#darkColor] '
                                       '| Scale #Scale#,#Scale#,0,0').format(width_multiplier)

    ini['MeterBackgroundTop']['Shape'] = ('Rectangle 3,3,({0}*186),25,2 | Fill Color #headerColor# | StrokeWidth 0 '
                                          '| Stroke Color [#darkColor] | Scale #Scale#,#Scale#,0,0').format(width_multiplier)
    ini['Rainmeter']['SkinWidth'] = '({0}*198*#Scale#)'.format(width_multiplier)
    ini['Rainmeter']['SkinHeight'] = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'
    ini['meterTitle']['W'] = '({0}*190*#Scale#)'.format(width_multiplier)
    ini['meterTitle']['X'] = '({0}*198*#Scale#)/2'.format(width_multiplier)


    # endregion

    # region Build Dump
    dump = '{0:<24} {1:>8} {2:>8}\n'.format("CATEGORY", "BUDGETED", "REMAINING")
    dump += f'{make_separator(44, "-")}\n'

    if len(categories_fetched) == 0:
        dump = "No budget warnings.\n"

    for item in categories_fetched:
        # unpack
        category_name, budgeted_warning, budgeted, balance = item
        dump += '{0:<24} {1:>8.2f} {2:>8.2f}\n'.format(category_name, budgeted, balance)

    # endregion
    # Size to actual content + the shared 2-row buffer so the last row
    # isn't clipped by the title/links bar overhead. See hud_jira for the
    # same pattern.
    ini['Variables']['ItemLines'] = str(compute_max_hud_lines(dump))

    total_budgeted = sum(item[2] for item in categories_fetched)
    total_balance = sum(item[3] for item in categories_fetched)

    return {
        "text": dump,
        "summary": "{0} budget warning(s) · budgeted ${1:.2f} · remaining ${2:.2f}".format(
            len(categories_fetched), total_budgeted, total_balance,
        ),
        "metrics": {
            "warnings": len(categories_fetched),
            "total_budgeted": round(total_budgeted, 2),
            "total_balance": round(total_balance, 2),
            "warning_threshold_pct": round(budget_percent_warning * 100, 2),
            "categories": [
                {
                    "name": name,
                    "budgeted": round(budgeted, 2),
                    "balance": round(balance, 2),
                }
                for name, _, budgeted, balance in categories_fetched
            ],
        },
        "links": {
            "budget_sgd": url_budget_sgd,
            "budget_php": url_budget_php,
        },
    }


def _sum_amount_by_day(
    rows,
    amount_field: str = "TOTAL PRICE",
    date_field: str = "DATE",
):
    """Group AppSheet INVOICE rows by day and sum `amount_field`.

    Dates are parsed as MM/DD/YYYY (the format AppSheet emits for date
    columns). Rows missing or with unparseable date/amount are skipped.
    Returns `{datetime.date: float}`.
    """
    totals: dict[date, float] = defaultdict(float)
    for row in rows:
        raw_date = row.get(date_field)
        raw_amount = row.get(amount_field)
        if not raw_date or raw_amount in (None, ""):
            continue
        try:
            day = datetime.strptime(str(raw_date), "%m/%d/%Y").date()
            amount = float(raw_amount)
        except (ValueError, TypeError):
            continue
        totals[day] += amount
    return dict(totals)


def _group_by_month(daily_totals):
    """Group `{date: amount}` into month buckets, most-recent month first.

    Within each month, days are ordered descending. Returns a list of
    `(month_label, [(date, amount), ...])` tuples where `month_label` is
    the uppercase full month name (e.g. "MAY", "APRIL").
    """
    by_month: dict[tuple[int, int], list[tuple[date, float]]] = {}
    for day, amount in sorted(daily_totals.items(), reverse=True):
        by_month.setdefault((day.year, day.month), []).append((day, amount))
    out = []
    for (year, month), entries in by_month.items():
        label = date(year, month, 1).strftime('%B').upper()
        out.append((label, entries))
    return out


_PC_DAILY_SALES_ROW_WIDTH = 24  # date(10) + 5-space gap + width-9 amount


def _render_pc_daily_sales_dump(daily_totals) -> str:
    """Render the dump body with one section per month + dash separator.

    Row width is the maximum that fits the HUD text area without wrapping.
    Touching `MeterDisplay W` to widen further requires also resizing the
    base template's `MeterBackground` / `MeterBackgroundTop` / `meterTitle`
    in lockstep — we keep the OANDA-exact width for that reason.
    """
    sep = "-" * _PC_DAILY_SALES_ROW_WIDTH
    blocks: list[str] = []
    for month_label, entries in _group_by_month(daily_totals):
        lines = [month_label, sep]
        for day, amount in entries:
            lines.append('{0}     {1:>9.2f}'.format(
                day.strftime('%d-%m-%Y'), amount))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


@SPROUT.task()
@log_result()
@init_meter(RAINMETER_CONFIG, hud_item_name='PC DAILY SALES',
            new_sections_dict=sections__pc_daily_sales, play_sound=False,
            schedule_categories=[ScheduleCategory.FINANCE, ])
@feed()
def show_pc_daily_sales(ini=ConfigHelperRainmeter(),
                        days: int = 60,
                        visible_lines: int = 10,
                        amount_field: str = "TOTAL PRICE",
                        date_field: str = "DATE",
                        **kwargs):
    """Gross daily sales for the last N days from the AppSheet INVOICE table.

    Sums `amount_field` (default "TOTAL PRICE") grouped by `date_field`
    day, then groups by calendar month with an uppercase month header and
    a 24-dash separator. The HUD shows `visible_lines` rows at a time;
    the rest is reachable via mouse-wheel scroll.
    """
    log.info("show_pc_daily_sales kwargs: %s", list(kwargs.keys()))

    # region Fetch invoices
    cfg_id__appsheet = kwargs.get('cfg_id__appsheet', APP_NAME_APPSHEET)
    cfg__appsheet = CONFIG_MANAGER.get(cfg_id__appsheet)

    service = ApiServiceAppSheetTables(cfg__appsheet)
    table = service.default_table or "INVOICE"
    result = service.find_rows(table=table)
    # endregion

    # region Aggregate by day, take last N days (most recent first)
    totals_by_day = _sum_amount_by_day(
        rows=[r.fields for r in result.rows],
        amount_field=amount_field,
        date_field=date_field,
    )
    last_n_days = dict(sorted(totals_by_day.items(), reverse=True)[:days])
    # endregion

    # region Build links — WEB → AppSheet app
    app_id = cfg__appsheet.app_data['default_app_id']
    web_url = 'https://www.appsheet.com/start/{0}'.format(app_id)
    ini['meterLink']['text'] = "WEB"
    ini['meterLink']['leftmouseupaction'] = '!Execute ["{0}" 3]'.format(web_url)
    ini['meterLink']['tooltiptext'] = web_url
    # endregion

    # region Compose dump (month-grouped — no [SCROLL FOR MORE] / [END] wrappers)
    dump = _render_pc_daily_sales_dump(last_n_days) or "(no invoices in window)"
    # endregion

    # region Set dimensions — mirror show_ynab_budgets_info's recipe so all
    # the widget-chrome rectangles (MeterBackground, MeterBackgroundTop,
    # meterTitle, SkinWidth/Height) scale with #Scale# in lockstep. The
    # earlier OANDA-style approach (W=180 unscaled while SkinWidth=198*#Scale#
    # was the base default) left a large empty band on the right of the chrome
    # whenever the user's #Scale# > 1. `(#ItemLines#+1)*22` adds one row of
    # buffer so the bottom row doesn't half-clip.
    width_multiplier = 0.9
    # Separator spans the inner content area (matches MeterDisplay W) so the
    # horizontal line under WEB reaches the right edge of the widget chrome.
    ini['meterSeperator']['W'] = '({0}*186*#Scale#)'.format(width_multiplier)

    ini['MeterDisplay']['W'] = '({0}*186*#Scale#)'.format(width_multiplier)
    ini['MeterDisplay']['H'] = '((42*#Scale#)+((#ItemLines#+4)*22)*#Scale#)'
    ini['MeterDisplay']['X'] = '14'
    ini['MeterDisplay']['MeasureName'] = 'MeasureScrollableText'

    ini['MeterBackground']['Shape'] = (
        'Rectangle 0,0,({0}*190),(36+((#ItemLines#+4)*22)),2 '
        '| Fill Color #fillColor# | StrokeWidth (1*#Scale#) '
        '| Stroke Color [#darkColor] | Scale #Scale#,#Scale#,0,0'
    ).format(width_multiplier)
    ini['MeterBackgroundTop']['Shape'] = (
        'Rectangle 3,3,({0}*186),25,2 | Fill Color #headerColor# '
        '| StrokeWidth 0 | Stroke Color [#darkColor] '
        '| Scale #Scale#,#Scale#,0,0'
    ).format(width_multiplier)

    ini['Rainmeter']['SkinWidth'] = '({0}*198*#Scale#)'.format(width_multiplier)
    ini['Rainmeter']['SkinHeight'] = '((42*#Scale#)+((#ItemLines#+4)*22)*#Scale#)'

    ini['meterTitle']['W'] = '({0}*190*#Scale#)'.format(width_multiplier)
    ini['meterTitle']['X'] = '({0}*198*#Scale#)/2'.format(width_multiplier)

    ini['Variables']['ItemLines'] = str(visible_lines)
    # endregion

    total_gross = sum(last_n_days.values())
    return {
        "text": dump,
        "summary": "{0} day(s) · gross {1:,.2f}".format(len(last_n_days), total_gross),
        "metrics": {
            "days": len(last_n_days),
            "total_gross": round(total_gross, 2),
            "rows": [
                {"date": d.strftime('%d-%m-%Y'), "amount": round(a, 2)}
                for d, a in last_n_days.items()
            ],
        },
        "links": {"web": web_url},
    }

