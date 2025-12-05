from workflows.hud.tasks.hud_forex import show_forex_account


def test__show_forex_account():
    show_forex_account("OANDA", calendar_cfg_id="GOOGLE_APPS")