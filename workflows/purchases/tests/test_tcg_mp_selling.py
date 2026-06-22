from datetime import datetime

from workflows.purchases.tasks.tcg_mp_selling import (generate_tcg_mappings, generate_audit_for_tcg_orders,
                                                      download_scryfall_bulk_data, generate_tcg_listings,
                                                      update_tcg_listings_prices,
                                                      reconcile_then_update_tcg_listings,
                                                      _norm_foil, _acquired_dt, _variant_key,
                                                      _same_variant, _group_by_variant)
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