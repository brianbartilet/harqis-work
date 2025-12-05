from workflows.hud.tasks.hud_tcg import show_tcg_orders


def test__show_tcg_orders():
    show_tcg_orders("TCG_MP", "SCRYFALL",
                    calendar_cfg_id="GOOGLE_APPS",
                    path_to_qr="G:\My Drive\TCG_MP")