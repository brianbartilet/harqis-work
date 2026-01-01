from workflows.hud.tasks.hud_finance import show_ynab_budgets_info


def test__show_ynab_budgets_info():
    show_ynab_budgets_info('YNAB', calendar_cfg_id="GOOGLE_APPS")