from workflows.hud.tasks.hud_tcg import show_pending_drop_off_orders


def test__show_pending_drop_off_orders():
    show_pending_drop_off_orders("TCG_MP", "SCRYFALL",
                                 calendar_cfg_id="GOOGLE_APPS",
                                 path_to_qr="G:\My Drive\TCG_MP")