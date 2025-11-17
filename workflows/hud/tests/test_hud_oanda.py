from workflows.hud.tasks.hud_oanda import show_account_information


def test__update_dashboard_trello_current_cards_info_trading():
    show_account_information("OANDA")