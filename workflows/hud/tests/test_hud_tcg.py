import pytest

from apps.tcg_mp.references.dto.listing import DtoWantToBuyListing
from apps.tcg_mp.references.web.api.buy import _parse_want_to_buy_listings
from workflows.hud.tasks.hud_tcg import (
    _is_acceptable_bid,
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
        worker_count=3,
    )


# ── Unit / function — _parse_want_to_buy_listings ─────────────────────────────
#
# Sample payload mirrors the real marketplace response observed against
# /buy/listed_item_filter on 2026-05-01:
#   { "status": 200, "data": { "message": "", "data": [...] }, "meta": {...} }
# Two `data` envelopes — the parser must hop both.

class _FakeResponse:
    """Stand-in for the framework's `IResponse` — only the `.data` attr matters."""
    def __init__(self, data):
        self.data = data


_SAMPLE_BID_FOIL_0 = {
    "id": 78063, "expdate": 1, "own_listing": 0, "buyer_id": 3241,
    "buyer_name": "alice", "buyer_type": "Buyer", "quantity": 2,
    "price": "3.00", "crd_condition": "NM", "crd_foil": "0",
    "crd_language": "EN", "country_code": "SG", "listed": 2478,
    "crd_setcode": "sos", "suspended": 0, "dropoff_available": 1,
    "total_bought": 469,
}

_SAMPLE_BID_FOIL_1 = {
    "id": 78772, "expdate": 1, "own_listing": 0, "buyer_id": 1309,
    "buyer_name": "bob", "buyer_type": "Buyer", "quantity": 3,
    "price": "15.00", "crd_condition": "NM", "crd_foil": "1",
    "crd_language": "EN", "country_code": "SG", "listed": 166,
    "crd_setcode": "sos", "suspended": 0, "dropoff_available": 1,
    "total_bought": 1006,
}

_REAL_RESPONSE_BODY = {
    "status": 200,
    "data": {
        "message": "",
        "data": [_SAMPLE_BID_FOIL_0, _SAMPLE_BID_FOIL_1],
    },
    "meta": {"total": 2},
}


def test__parse_want_to_buy_listings__real_two_envelope_shape():
    out = _parse_want_to_buy_listings(_FakeResponse(_REAL_RESPONSE_BODY))
    assert len(out) == 2
    assert all(isinstance(x, DtoWantToBuyListing) for x in out)
    assert out[0].id == 78063
    assert out[0].price == "3.00"
    assert out[0].buyer_name == "alice"
    assert out[1].id == 78772
    assert out[1].crd_foil == "1"


def test__parse_want_to_buy_listings__no_buyers_returns_empty_string():
    """The marketplace returns `data.data.data == ""` (string!) when no buyers exist."""
    body = {"status": 200, "data": {"message": "", "data": ""}, "meta": {"total": 0}}
    assert _parse_want_to_buy_listings(_FakeResponse(body)) == []


def test__parse_want_to_buy_listings__no_buyers_returns_empty_list():
    body = {"status": 200, "data": {"message": "", "data": []}, "meta": {"total": 0}}
    assert _parse_want_to_buy_listings(_FakeResponse(body)) == []


def test__parse_want_to_buy_listings__skips_non_dict_items():
    body = {
        "status": 200,
        "data": {"message": "", "data": [_SAMPLE_BID_FOIL_0, "garbage", None, 42]},
        "meta": {"total": 1},
    }
    out = _parse_want_to_buy_listings(_FakeResponse(body))
    assert len(out) == 1
    assert out[0].id == 78063


def test__parse_want_to_buy_listings__ignores_unknown_dto_fields():
    """Server adds a new field — parser must silently drop it, not crash."""
    bid = {**_SAMPLE_BID_FOIL_0, "future_field_v2": "wat"}
    body = {"status": 200, "data": {"message": "", "data": [bid]}, "meta": {"total": 1}}
    out = _parse_want_to_buy_listings(_FakeResponse(body))
    assert len(out) == 1
    assert out[0].id == 78063
    assert not hasattr(out[0], "future_field_v2")


def test__parse_want_to_buy_listings__handles_none_response():
    assert _parse_want_to_buy_listings(_FakeResponse(None)) == []


def test__parse_want_to_buy_listings__handles_500_error_payload():
    """Marketplace 500 shape — body is a dict but inner `data` is empty string."""
    body = {
        "status": 500,
        "data": {"message": "Unexpected token p in JSON at position 0", "data": ""},
        "meta": {"total": 0},
    }
    assert _parse_want_to_buy_listings(_FakeResponse(body)) == []


def test__parse_want_to_buy_listings__handles_pre_unwrapped_envelope():
    """If the framework hands back the inner envelope directly, still parse."""
    inner = {"message": "", "data": [_SAMPLE_BID_FOIL_0]}
    out = _parse_want_to_buy_listings(_FakeResponse(inner))
    assert len(out) == 1
    assert out[0].id == 78063


# ── Unit / function — _is_acceptable_bid ──────────────────────────────────────

@pytest.mark.parametrize("my_price,bid,pct,expected", [
    (15.74, 14.50, 10.0, True),    # within 10% discount → match
    (15.74, 13.00, 10.0, False),   # ~17% discount → reject
    (10.00, 12.00, 10.0, True),    # buyer pays MORE than list → always match
    (0.0,    5.00, 10.0, False),   # zero list price → never match
    (-1.0,   5.00, 10.0, False),   # negative list price → never match
    (10.00, 10.00,  0.0, True),    # zero threshold + exact match → match
    (10.00,  9.99,  0.0, False),   # zero threshold + 1c below → reject
    (10.00,  5.00, 50.0, True),    # 50% threshold → bid at half list ok
    (10.00,  4.99, 50.0, False),   # 50% threshold + just below → reject
])
def test__is_acceptable_bid(my_price, bid, pct, expected):
    assert _is_acceptable_bid(my_price=my_price, bid_price=bid, discount_pct=pct) is expected
