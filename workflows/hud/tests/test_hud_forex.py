from workflows.hud.tasks.hud_forex import show_forex_account


def test__show_forex_account():
    show_forex_account(cfg_id__oanda="OANDA", cfg_id__calendar="GOOGLE_APPS")