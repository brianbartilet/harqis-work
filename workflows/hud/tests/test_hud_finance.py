from workflows.hud.tasks.hud_finance import show_ynab_budgets_info


def test__show_ynab_budgets_info():
    show_ynab_budgets_info(cfg_id__ynab='YNAB', cfg_id__calendar="GOOGLE_APPS")