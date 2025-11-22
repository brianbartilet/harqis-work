from workflows.hud.tasks.hud_forex import show_account_information


def test__show_account_information():
    show_account_information("OANDA", calendar_cfg_id="GOOGLE_APPS")