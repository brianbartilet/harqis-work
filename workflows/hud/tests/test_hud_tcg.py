from workflows.hud.tasks.hud_tcg import show_tcg_orders, show_tcg_orders_no_schedule


def test__show_tcg_orders():
    show_tcg_orders(cfg_id__tcg_mp="TCG_MP",
                    cfg_id__scryfall="SCRYFALL",
                    cfg_id__calendar="GOOGLE_APPS")

def test__show_tcg_orders_adhoc():
    show_tcg_orders_no_schedule(cfg_id__tcg_mp="TCG_MP",
                    cfg_id__scryfall="SCRYFALL")