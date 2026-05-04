from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.data.strings import make_separator
from core.utilities.logging.custom_logger import logger as log

from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_meter
from apps.desktop.helpers.feed import feed

from apps.ynab.references.web.api.budgets import ApiServiceYNABBudgets
from apps.ynab.config import APP_NAME as APP_NAME_YNAB
from apps.ynab.references.constants import YNAB_MILLIUNITS

from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.apps_config import CONFIG_MANAGER

from apps.google_apps.references.constants import ScheduleCategory

from workflows.hud.helpers.sizing import compute_max_hud_lines
from workflows.hud.tasks.sections import sections__ynab


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

