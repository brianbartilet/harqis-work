import pytest

from workflows.hud.tasks.hud_tcg import (
    show_tcg_orders,
    show_tcg_sell_cart,
)


# ── Workflow (integration) ────────────────────────────────────────────────────

def test__show_tcg_orders():
    show_tcg_orders(cfg_id__tcg_mp="TCG_MP",
                    cfg_id__scryfall="SCRYFALL",
                    cfg_id__calendar="GOOGLE_APPS")


def test__show_tcg_sell_cart_dry_run():
    """Live call against the marketplace with dry_run=True — no carts mutated."""
    show_tcg_sell_cart(
        cfg_id__tcg_mp="TCG_MP",
        discount_threshold_pct=10.0,
        dry_run=True,
        limit=3,
        worker_count=2,
    )


@pytest.mark.skip(
    reason="Live mutation — calls /want_to_buy/cart/add and queues real bids in the seller's sell cart."
)
def test__show_tcg_sell_cart_live_add():
    show_tcg_sell_cart(
        cfg_id__tcg_mp="TCG_MP",
        discount_threshold_pct=10.0,
        dry_run=False,
        limit=1,
        worker_count=1,
    )


