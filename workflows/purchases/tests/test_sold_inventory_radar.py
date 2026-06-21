import pytest

import csv

from workflows.purchases.tasks.sold_inventory_radar import (
    radar_sold_inventory,
    _norm_foil,
    _to_int,
    _parse_note,
    _extract_order_items,
    _build_sold_index,
    _match_candidate,
    _candidate_to_row,
    _write_csv,
    CSV_FIELDS,
)


# ── Workflow (integration) ────────────────────────────────────────────────────

def test__radar_sold_inventory_dry_run():
    """Read-only pass — polls orders/inventory/listings, writes the review list,
    makes NO mutations. Needs live TCG_MP + ECHO_MTG config."""
    radar_sold_inventory(
        dry_run=True,
        cfg_id__tcg_mp="TCG_MP",
        cfg_id__echo_mtg="ECHO_MTG",
        cfg_id__echo_mtg_fe="ECHO_MTG_FE",
        last_x_days=30,
        limit=10,
    )


@pytest.mark.skip(reason="Destructive — marks sold, removes EchoMTG inventory, and delists on TCG MP")
def test__radar_sold_inventory_apply():
    radar_sold_inventory(
        dry_run=False,
        cfg_id__tcg_mp="TCG_MP",
        cfg_id__echo_mtg="ECHO_MTG",
        cfg_id__echo_mtg_fe="ECHO_MTG_FE",
    )


# ── Unit / function ───────────────────────────────────────────────────────────

def test__norm_foil_variants():
    assert _norm_foil(1) == 1
    assert _norm_foil("1") == 1
    assert _norm_foil("foil") == 1
    assert _norm_foil(0) == 0
    assert _norm_foil("") == 0
    assert _norm_foil(None) == 0


def test__to_int_coercion():
    assert _to_int("42") == 42
    assert _to_int(42) == 42
    assert _to_int("") is None
    assert _to_int(None) is None
    assert _to_int("abc") is None


def test__parse_note_valid():
    resp = {"note": {"note": '{"tcg_mp_listing_id": 5, "tcg_mp_card_id": 9}'}}
    note = _parse_note(resp)
    assert note["tcg_mp_listing_id"] == 5
    assert note["tcg_mp_card_id"] == 9


def test__parse_note_not_found_and_garbage():
    assert _parse_note({"status": "error", "note": "not found"}) is None
    assert _parse_note({"note": {"note": "not-json"}}) is None
    assert _parse_note(None) is None


def test__extract_order_items_defensive_keys():
    detail = {
        "order_id": "000123",
        "status": "Completed",
        "items": [
            {"product_id": 100, "listing_id": 7, "crd_foil": "1", "crd_name": "Sol Ring", "qty": 1, "price": "4.00"},
            {"productId": 200, "foil": 0, "name": "Llanowar Elves", "quantity": 2},
            "not-a-dict",
        ],
    }
    items = _extract_order_items(detail)
    assert len(items) == 2
    assert items[0]["product_id"] == 100 and items[0]["listing_id"] == 7 and items[0]["foil"] == 1
    assert items[1]["product_id"] == 200 and items[1]["qty"] == 2 and items[1]["foil"] == 0


def test__extract_order_items_empty():
    assert _extract_order_items({}) == []
    assert _extract_order_items({"items": "nope"}) == []


def test__build_sold_index_keys():
    details = [{
        "order_id": "0001", "status": "Completed",
        "items": [{"product_id": 100, "listing_id": 7, "crd_foil": "1", "crd_name": "Sol Ring", "price": "4.00"}],
    }]
    idx = _build_sold_index(details)
    assert 7 in idx["by_listing"]
    assert (100, 1) in idx["by_product"]
    assert idx["by_listing"][7][0]["order_id"] == "0001"


def test__match_candidate_high_confidence_listing():
    item = {"emid": "1", "inventory_id": "i1", "note_id": "n1", "foil": 1}
    note = {"tcg_mp_listing_id": 7, "tcg_mp_card_id": 100}
    sold_index = _build_sold_index([{
        "order_id": "0001", "status": "Cancelled",
        "items": [{"product_id": 100, "listing_id": 7, "crd_foil": "1", "crd_name": "Sol Ring", "price": "4"}],
    }])
    c = _match_candidate(item, note, active_listing_ids={7},
                         active_product_foil={(100, 1)}, sold_index=sold_index)
    assert c is not None
    assert c["confidence"] == "high"
    assert c["card_name"] == "Sol Ring"
    assert c["matched_orders"][0]["order_id"] == "0001"
    # the assessment explains the flag, naming the listing and the order
    assert c["assessment"].startswith("HIGH")
    assert "0001" in c["assessment"] and "listing 7" in c["assessment"]


def test__match_candidate_medium_confidence_product():
    item = {"emid": "2", "inventory_id": "i2", "note_id": "n2", "foil": 0}
    note = {"tcg_mp_listing_id": 999, "tcg_mp_card_id": 200}  # listing not in sold set
    sold_index = _build_sold_index([{
        "order_id": "0002", "status": "Completed",
        "items": [{"product_id": 200, "foil": 0, "name": "Llanowar Elves"}],
    }])
    c = _match_candidate(item, note, active_listing_ids=set(),
                         active_product_foil={(200, 0)}, sold_index=sold_index)
    assert c is not None and c["confidence"] == "medium"
    assert c["assessment"].startswith("MEDIUM") and "non-foil" in c["assessment"]


def test__match_candidate_not_listed_returns_none():
    item = {"emid": "3", "inventory_id": "i3", "note_id": "n3", "foil": 0}
    note = {"tcg_mp_listing_id": 7, "tcg_mp_card_id": 100}
    sold_index = _build_sold_index([{
        "order_id": "0003", "status": "Completed",
        "items": [{"product_id": 100, "listing_id": 7, "foil": 0, "name": "X"}],
    }])
    # Not in any active listing set → not a candidate even though it was sold.
    c = _match_candidate(item, note, active_listing_ids=set(),
                         active_product_foil=set(), sold_index=sold_index)
    assert c is None


def test__match_candidate_listed_but_not_sold_returns_none():
    item = {"emid": "4", "inventory_id": "i4", "note_id": "n4", "foil": 0}
    note = {"tcg_mp_listing_id": 8, "tcg_mp_card_id": 300}
    c = _match_candidate(item, note, active_listing_ids={8},
                         active_product_foil={(300, 0)}, sold_index={"by_listing": {}, "by_product": {}})
    assert c is None


def _sample_candidate():
    return {
        "emid": "1", "inventory_id": "i1", "note_id": "n1", "foil": 1,
        "card_name": "Sol Ring", "confidence": "high",
        "tcg_mp_listing_id": 7, "tcg_mp_card_id": 100,
        "acquired_price": "1.00", "sold_price": "4.00", "applied": False,
        "matched_orders": [{"order_id": "0001", "status": "Completed", "qty": 1, "price": "4.00"}],
        "echo_item": {"set": "C21", "condition": "NM", "acquired_price": "1.00",
                      "date_acquired": "2026-01-02 10:00:00", "price_change": "5"},
        "note": {"scryfall_guid": "abc", "tcgplayer_id": 555, "tcg_mp_card_id": 100,
                 "tcg_mp_listing_id": 7, "tcg_mp_selling_price": 4.0, "tcg_price": 3.5,
                 "last_updated": "2026-06-01"},
        "listing": {"listing_id": 7, "product_id": 100, "name": "Sol Ring",
                    "setname": "Commander 2021", "price": "4.20", "quantity": 2,
                    "crd_condition": "NM", "crd_foil": "1"},
        "actions": {"mark_sold": "ok", "remove_inventory": "ok", "delist": "ok"},
    }


def test__candidate_to_row_has_both_sides():
    row = _candidate_to_row(_sample_candidate())
    # every declared column is present
    assert set(row.keys()) == set(CSV_FIELDS)
    # EchoMTG side
    assert row["emid"] == "1" and row["echo_set"] == "C21" and row["echo_condition"] == "NM"
    # note join key
    assert row["note_tcg_mp_listing_id"] == 7 and row["note_scryfall_guid"] == "abc"
    # TCG MP live listing
    assert row["listing_id"] == 7 and row["listing_price"] == "4.20" and row["listing_quantity"] == 2
    # sold-order evidence + action results
    assert "0001(Completed" in row["sold_in_orders"]
    assert "mark_sold:ok" in row["action_results"]


def test__write_csv_roundtrip(tmp_path):
    out = tmp_path / "radar.csv"
    _write_csv(out, [_sample_candidate()])
    with open(out, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    assert rows[0]["card_name"] == "Sol Ring"
    assert rows[0]["listing_set"] == "Commander 2021"
    assert list(rows[0].keys()) == CSV_FIELDS


def test__write_csv_empty_writes_header_only(tmp_path):
    out = tmp_path / "empty.csv"
    _write_csv(out, [])
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1  # header only
    assert lines[0].split(",")[0] == "card_name"
