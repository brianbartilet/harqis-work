from workflows.hud.tasks.hud_tcg import show_tcg_orders


def test__show_tcg_orders():
    show_tcg_orders(cfg_id__tcg_mp="TCG_MP",
                    cfg_id__scryfall="SCRYFALL",
                    cfg_id__calendar="GOOGLE_APPS")