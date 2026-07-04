from datetime import datetime

from workflows.purchases.tasks.tcg_mp_selling import (generate_tcg_mappings, generate_audit_for_tcg_orders,
                                                      download_scryfall_bulk_data, generate_tcg_listings,
                                                      update_tcg_listings_prices,
                                                      reconcile_then_update_tcg_listings,
                                                      _norm_foil, _acquired_dt, _variant_key,
                                                      _same_variant, _group_by_variant,
                                                      _listing_matches_variant, _find_live_variant_listings, _choose_primary_listing,
                                                      _remove_duplicate_variant_listings,
                                                      _choose_update_representative,
                                                      _available_listing_quantity,
                                                      _safe_listing_quantity,
                                                      _order_detail_items,
                                                      _reserved_quantities_by_product_foil,
                                                      HANDED_OFF_ORDER_STATUSES)
from apps.apps_config import CONFIG_MANAGER
from apps.tcg_mp.references.web.api.publish import ApiServiceTcgMpPublish


#  region Value
def test__generate_tcg_mappings():
    generate_tcg_mappings(cfg_id__tcg_mp="TCG_MP",
                          cfg_id__echo_mtg="ECHO_MTG",
                          cfg_id__echo_mtg_fe="ECHO_MTG_FE",
                          cfg_id__scryfall="SCRYFALL",
                          limit=5
                          )

def test__generate_tcg_mappings_force():
    generate_tcg_mappings(cfg_id__tcg_mp="TCG_MP",
                          cfg_id__echo_mtg="ECHO_MTG",
                          cfg_id__echo_mtg_fe="ECHO_MTG_FE",
                          cfg_id__scryfall="SCRYFALL",
                          force_generate=True
                          )

def test__generate_tcg_listings():
    generate_tcg_listings(cfg_id__tcg_mp="TCG_MP",
                          cfg_id__echo_mtg="ECHO_MTG",
                          cfg_id__echo_mtg_fe="ECHO_MTG_FE",
                          # limit=5
                          )

def test__update_tcg_listings_prices():
    update_tcg_listings_prices(cfg_id__tcg_mp="TCG_MP",
                               cfg_id__echo_mtg="ECHO_MTG",
                               cfg_id__echo_mtg_fe="ECHO_MTG_FE",
                               worker_count=3
                               )
#  endregion

#  region Bulk
def test__generate_tcg_mappings_bulk():
    generate_tcg_mappings(cfg_id__tcg_mp="TCG_MP",
                          cfg_id__echo_mtg="ECHO_MTG_BULK",
                          cfg_id__echo_mtg_fe="ECHO_MTG_FE_BULK",
                          cfg_id__scryfall="SCRYFALL",
                          limit=5
                          )

def test__generate_tcg_mappings_bulk_force():
    generate_tcg_mappings(cfg_id__tcg_mp="TCG_MP",
                          cfg_id__echo_mtg="ECHO_MTG_BULK",
                          cfg_id__echo_mtg_fe="ECHO_MTG_FE_BULK",
                          cfg_id__scryfall="SCRYFALL",
                          force_generate=True
                          )

def test__generate_tcg_listings_bulk():
    generate_tcg_listings(cfg_id__tcg_mp="TCG_MP",
                          cfg_id__echo_mtg="ECHO_MTG_BULK",
                          cfg_id__echo_mtg_fe="ECHO_MTG_FE_BULK"
                          )

def test__update_tcg_listings_prices_bulk():
    update_tcg_listings_prices(cfg_id__tcg_mp="TCG_MP",
                               cfg_id__echo_mtg="ECHO_MTG_BULK",
                               cfg_id__echo_mtg_fe="ECHO_MTG_FE_BULK",
                               worker_count=4
                               )
#  endregion

def test__generate_audit_for_tcg_orders():
    generate_audit_for_tcg_orders(cfg_id__tcg_mp="TCG_MP")

def test__download_scryfall_bulk_data():
    download_scryfall_bulk_data(cfg_id__scryfall="SCRYFALL")

def test__edit_listing_non_existing_id():
    cfg = CONFIG_MANAGER.get("TCG_MP")
    api = ApiServiceTcgMpPublish(cfg)
    result = api.edit_listing(listing_id=623450, price=1.0)
    assert result == "" or result is None


# ── Unit / variant-identity helpers ───────────────────────────────────────────

def test__norm_foil_variants():
    assert _norm_foil(1) == 1
    assert _norm_foil("foil") == 1
    assert _norm_foil(0) == 0
    assert _norm_foil("") == 0
    assert _norm_foil(None) == 0


def test__acquired_dt_parses_and_falls_back():
    assert _acquired_dt({"date_acquired": "2026-06-22 10:30:00"}) == datetime(2026, 6, 22, 10, 30, 0)
    assert _acquired_dt({"date_acquired_html": "2026-06-21"}) == datetime(2026, 6, 21, 0, 0, 0)
    assert _acquired_dt({"date_acquired": "6/21/2026"}) == datetime(2026, 6, 21, 0, 0, 0)
    # Missing / malformed never raises — sorts oldest.
    assert _acquired_dt({}) == datetime.min
    assert _acquired_dt({"date_acquired": "garbage"}) == datetime.min


def test__variant_key_distinguishes_finish_language_condition():
    base = {"emid": "100", "foil": 0, "language": "EN", "condition": "NM"}
    assert _variant_key(base) == ("100", 0, "EN", "NM")
    # Foil, language and condition each produce a distinct key.
    assert _variant_key({**base, "foil": 1}) != _variant_key(base)
    assert _variant_key({**base, "language": "JP"}) != _variant_key(base)
    assert _variant_key({**base, "condition": "LP"}) != _variant_key(base)


def test__variant_key_defaults_and_run_language():
    # Missing language/condition fall back to EN / NM (matching add_listing defaults).
    assert _variant_key({"emid": "1", "foil": 0}) == ("1", 0, "EN", "NM")
    # A per-run language override folds in only when the card has none.
    assert _variant_key({"emid": "1", "foil": 0}, default_language="JP") == ("1", 0, "JP", "NM")
    assert _variant_key({"emid": "1", "foil": 0, "language": "EN"}, default_language="JP") == ("1", 0, "EN", "NM")


def test__same_variant_foil_authoritative_and_tolerant():
    coll = {"emid": "100", "foil": 0, "language": "EN", "condition": "NM"}
    # Foil mismatch never matches.
    assert _same_variant(coll, {"foil": 1}) is False
    # A sparse search_card row (no language/condition) still matches its copy —
    # this is what prevents quantity collapsing to 0.
    assert _same_variant(coll, {"foil": 0}) is True
    assert _same_variant(coll, {"foil": "0"}) is True
    # When BOTH sides carry a distinguishing field, they split.
    assert _same_variant(coll, {"foil": 0, "condition": "LP"}) is False
    assert _same_variant(coll, {"foil": 0, "language": "JP"}) is False
    assert _same_variant(coll, {"foil": 0, "condition": "NM", "language": "EN"}) is True


def test__group_by_variant_consolidates_and_splits():
    cards = [
        {"emid": "100", "foil": 0, "inventory_id": "a"},   # NM/EN
        {"emid": "100", "foil": 0, "inventory_id": "b"},   # duplicate -> same group
        {"emid": "100", "foil": 1, "inventory_id": "c"},   # foil -> own group
        {"emid": "100", "foil": 0, "condition": "LP", "inventory_id": "d"},  # condition -> own group
        {"emid": "200", "foil": 0, "inventory_id": "e"},   # other card
    ]
    groups = _group_by_variant(cards)
    assert len(groups) == 4
    nm_group = groups[("100", 0, "EN", "NM")]
    assert {c["inventory_id"] for c in nm_group} == {"a", "b"}


def test__choose_update_representative_prefers_noted_copy():
    group = [
        {"inventory_id": "note-less", "note_id": 0, "date_acquired_html": "2026-06-25"},
        {"inventory_id": "noted", "note_id": 219818, "date_acquired_html": "2026-06-21"},
    ]
    assert _choose_update_representative(group)["inventory_id"] == "noted"


def test__choose_update_representative_uses_latest_noted_copy():
    group = [
        {"inventory_id": "older", "note_id": 1, "date_acquired_html": "2026-06-20"},
        {"inventory_id": "newer", "note_id": 2, "date_acquired_html": "2026-06-25"},
    ]
    assert _choose_update_representative(group)["inventory_id"] == "newer"


class _Listing:
    def __init__(self, listing_id, product_id=787650, quantity=1,
                 foil="0", language="EN", condition="NM"):
        self.listing_id = listing_id
        self.product_id = product_id
        self.quantity = quantity
        self.crd_foil = foil
        self.crd_language = language
        self.crd_condition = condition


class _Publish:
    def __init__(self):
        self.removed = []

    def remove_listings(self, ids):
        self.removed.append(ids)


def test__variant_key_uses_echo_lang_field():
    card = {"emid": "174033", "foil": 0, "lang": "JP", "condition": "NM"}
    assert _variant_key(card) == ("174033", 0, "JP", "NM")


def test__same_variant_compares_language_or_lang():
    assert _same_variant(
        {"emid": "174033", "foil": 0, "lang": "EN", "condition": "NM"},
        {"emid": "174033", "foil": 0, "language": "EN", "condition": "NM"},
    ) is True
    assert _same_variant(
        {"emid": "174033", "foil": 0, "lang": "JP", "condition": "NM"},
        {"emid": "174033", "foil": 0, "language": "EN", "condition": "NM"},
    ) is False


def test__listing_matches_variant_by_product_finish_language_condition():
    listing = _Listing(785652, quantity=3)
    assert _listing_matches_variant(
        listing, product_id=787650, foil=0, language="EN", condition="NM"
    ) is True
    assert _listing_matches_variant(
        listing, product_id=787650, foil=1, language="EN", condition="NM"
    ) is False
    assert _listing_matches_variant(
        listing, product_id=787650, foil=0, language="JP", condition="NM"
    ) is False


class _ViewReturnsRawResponse:
    def get_listings(self):
        return object()


class _ViewReturnsListings:
    def get_listings(self):
        return [_Listing(785652, quantity=3), _Listing(785650, quantity=2, language="JP")]


def test__find_live_variant_listings_returns_empty_for_raw_response():
    assert _find_live_variant_listings(
        _ViewReturnsRawResponse(), product_id=787650, foil=0,
        language="EN", condition="NM"
    ) == []


def test__find_live_variant_listings_filters_matching_variants():
    matches = _find_live_variant_listings(
        _ViewReturnsListings(), product_id=787650, foil=0,
        language="EN", condition="NM"
    )
    assert [m.listing_id for m in matches] == [785652]


def test__choose_primary_listing_prefers_note_listing_then_highest_quantity():
    stale = _Listing(785650, quantity=2)
    current = _Listing(785652, quantity=3)
    assert _choose_primary_listing([stale, current], preferred_listing_id=785650) is stale
    assert _choose_primary_listing([stale, current], preferred_listing_id=0) is current


def test__remove_duplicate_variant_listings_keeps_primary():
    publish = _Publish()
    stale = _Listing(785650, quantity=2)
    current = _Listing(785652, quantity=3)
    removed = _remove_duplicate_variant_listings(publish, [stale, current], 785652)
    assert removed == [785650]
    assert publish.removed == [[785650]]

class _OrderPage:
    def __init__(self, data):
        self.data = data


class _ReservedOrderService:
    def get_orders(self, by_status):
        return [_OrderPage([{"order_id": "0001"}, {"order_id": "0002"}])]

    def get_order_detail(self, order_id):
        quantities = {"0001": 2, "0002": 1}
        return {
            "order_id": order_id,
            "items": [
                {"product_id": 787544, "crd_foil": "0", "qty": quantities[order_id]},
                {"product_id": 999999, "crd_foil": "1", "qty": 1},
            ],
        }


def test__order_detail_items_extracts_product_foil_quantity():
    detail = {"items": [{"productId": "787544", "foil": "0", "quantity": "2"}]}
    assert _order_detail_items(detail) == [{"product_id": 787544, "foil": 0, "qty": 2}]


def test__reserved_quantities_sum_pending_commitments_by_product_and_foil():
    reserved = _reserved_quantities_by_product_foil(_ReservedOrderService())
    assert reserved[(787544, 0)] == 6  # two pending statuses each return qty 2 + qty 1
    assert reserved[(999999, 1)] == 4


def test__available_listing_quantity_subtracts_pending_commitments():
    reserved = {(787544, 0): 2}
    assert _available_listing_quantity(3, reserved, 787544, 0) == 1
    assert _available_listing_quantity(2, reserved, 787544, 0) == 0
    assert _available_listing_quantity(2, reserved, 787544, 1) == 2


def test__safe_listing_quantity_caps_to_live_listing_for_handed_off_orders():
    pending = {}
    handed_off = {(787544, 0): 1}
    assert _safe_listing_quantity(
        2, pending, handed_off, 787544, 0, live_quantity=1
    ) == 1


def test__safe_listing_quantity_subtracts_handed_off_when_listing_is_gone():
    pending = {}
    handed_off = {(787544, 0): 1}
    assert _safe_listing_quantity(
        1, pending, handed_off, 787544, 0, live_quantity=None
    ) == 0


def test__safe_listing_quantity_does_not_double_subtract_after_radar_removed_copy():
    pending = {}
    handed_off = {(787544, 0): 1}
    assert _safe_listing_quantity(
        1, pending, handed_off, 787544, 0, live_quantity=1
    ) == 1


def test__handed_off_statuses_match_dropoff_or_later_flow():
    labels = {status.label for status in HANDED_OFF_ORDER_STATUSES}
    assert "Pending Payment" not in labels
    assert "Pending Drop Off" not in labels
    assert "Cancelled" not in labels
    assert {"Dropped Off", "Shipped", "In Transit", "Arrived Branch", "Picked Up", "Completed", "Not Received"} <= labels

