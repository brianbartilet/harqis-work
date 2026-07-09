import pytest

import csv

import workflows.purchases.tasks.sold_inventory_radar as radar_module
from apps.tcg_mp.references.dto.order import EnumTcgOrderStatus
from workflows.purchases.tasks.sold_inventory_radar import (
    radar_sold_inventory,
    apply_radar_approvals,
    _norm_foil,
    _to_int,
    _status_label,
    _status_is_allowed,
    _copy_has_listing_note,
    _owned_counts,
    _reconcile_listing,
    _parse_note,
    _extract_order_items,
    _build_sold_index,
    _sold_quantity_budgets,
    _claim_sold_unit,
    _match_candidate,
    _candidate_to_row,
    _write_csv,
    _gather_es_order_details,
    _gather_live_order_details,
    CSV_FIELDS,
    DEFAULT_SOLD_STATUSES,
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


def test__build_sold_index_handles_multi_item_order_without_listing_ids():
    detail = {
        "order_id": "0000366974",
        "status": 3,
        "items": [
            {"product_id": 763727, "crd_foil": "0", "crd_name": "Leyline", "qty": 1},
            {"product_id": 1135109, "crd_foil": "0", "crd_name": "The Sentry", "qty": 1},
            {"product_id": 1135251, "crd_foil": "1", "crd_name": "Origin", "qty": 1},
            {"product_id": 1135166, "crd_foil": "1", "crd_name": "Warleader's Call", "qty": 1},
        ],
    }
    idx = _build_sold_index([detail])
    assert idx["by_listing"] == {}
    assert set(idx["by_product"]) == {
        (763727, 0), (1135109, 0), (1135251, 1), (1135166, 1)
    }


def test__sold_quantity_budget_limits_consolidated_listing_to_sold_qty():
    idx = _build_sold_index([{
        "order_id": "0001", "status": "Completed",
        "items": [{"product_id": 100, "listing_id": 7, "foil": 0, "qty": 1}],
    }])
    budgets = _sold_quantity_budgets(idx)
    note = {"tcg_mp_listing_id": 7, "tcg_mp_card_id": 100}

    assert _claim_sold_unit(note, 0, budgets) is True
    assert _claim_sold_unit(note, 0, budgets) is False
    assert budgets["by_listing"][7] == 0
    assert budgets["by_product"][(100, 0)] == 0


def test__sold_quantity_budget_allows_each_item_in_multi_item_order():
    idx = _build_sold_index([{
        "order_id": "0000366974", "status": "Completed",
        "items": [
            {"product_id": 763727, "foil": 0, "qty": 1},
            {"product_id": 1135109, "foil": 0, "qty": 1},
            {"product_id": 1135251, "foil": 1, "qty": 1},
            {"product_id": 1135166, "foil": 1, "qty": 1},
        ],
    }])
    budgets = _sold_quantity_budgets(idx)

    assert _claim_sold_unit({"tcg_mp_card_id": 763727}, 0, budgets) is True
    assert _claim_sold_unit({"tcg_mp_card_id": 1135109}, 0, budgets) is True
    assert _claim_sold_unit({"tcg_mp_card_id": 1135251}, 1, budgets) is True
    assert _claim_sold_unit({"tcg_mp_card_id": 1135166}, 1, budgets) is True
    assert _claim_sold_unit({"tcg_mp_card_id": 763727}, 0, budgets) is False


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
    assert c["detection"] == "sold_still_listed"
    assert "delist" in c["recommended_action"]
    assert c["card_name"] == "Sol Ring"
    assert c["matched_orders"][0]["order_id"] == "0001"
    # the assessment explains the flag, naming the listing and the order
    assert c["assessment"].startswith("HIGH")
    assert "0001" in c["assessment"] and "listing 7" in c["assessment"]


def test__match_candidate_listing_gone_high_when_product_sold():
    """Note maps a listing that is no longer active, and the product appears in a
    sold order → high-confidence listing_gone (mark sold + remove, no delist)."""
    item = {"emid": "5", "inventory_id": "i5", "note_id": "n5", "foil": 0}
    note = {"tcg_mp_listing_id": 738828, "tcg_mp_card_id": 945147}
    sold_index = _build_sold_index([{
        "order_id": "0009", "status": "Completed",
        "items": [{"product_id": 945147, "foil": 0, "name": "Orphaned Card"}],
    }])
    c = _match_candidate(item, note, active_listing_ids={111},        # 738828 NOT active
                         active_product_foil={(999, 0)}, sold_index=sold_index,
                         product_candidate_count=1)
    assert c is not None
    assert c["detection"] == "listing_gone" and c["confidence"] == "high"
    assert "delist" not in c["recommended_action"]      # listing already gone
    assert c["assessment"].startswith("HIGH")


def test__match_candidate_listing_gone_medium_when_product_sold_but_ambiguous():
    """Product-only evidence is not enough for auto-action when multiple EchoMTG
    candidates map to the same product/foil."""
    item = {"emid": "5", "inventory_id": "i5", "note_id": "n5", "foil": 0}
    note = {"tcg_mp_listing_id": 738828, "tcg_mp_card_id": 945147}
    sold_index = _build_sold_index([{
        "order_id": "0009", "status": "Completed",
        "items": [{"product_id": 945147, "foil": 0, "name": "Ambiguous Card"}],
    }])
    c = _match_candidate(item, note, active_listing_ids={111},
                         active_product_foil={(999, 0)}, sold_index=sold_index,
                         product_candidate_count=2)
    assert c is not None
    assert c["detection"] == "listing_gone" and c["confidence"] == "medium"
    assert c["assessment"].startswith("MEDIUM")


def test__match_candidate_listing_gone_low_when_uncorroborated():
    """Listing no longer active and no sold order found → low-confidence orphan."""
    item = {"emid": "6", "inventory_id": "i6", "note_id": "n6", "foil": 0}
    note = {"tcg_mp_listing_id": 738828, "tcg_mp_card_id": 945147}
    c = _match_candidate(item, note, active_listing_ids={111}, active_product_foil={(222, 0)},
                         sold_index={"by_listing": {}, "by_product": {}})
    assert c is not None
    assert c["detection"] == "listing_gone" and c["confidence"] == "low"
    assert c["assessment"].startswith("LOW")


def test__match_candidate_no_listing_mapped_returns_none():
    """No tcg_mp_listing_id mapped and not listed → nothing to infer."""
    item = {"emid": "7", "inventory_id": "i7", "note_id": "n7", "foil": 0}
    note = {"tcg_mp_listing_id": 0, "tcg_mp_card_id": 945147}
    c = _match_candidate(item, note, active_listing_ids=set(), active_product_foil=set(),
                         sold_index={"by_listing": {}, "by_product": {}})
    assert c is None


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


def test__match_candidate_high_confidence_product_when_only_echo_candidate():
    item = {"emid": "2", "inventory_id": "i2", "note_id": "n2", "foil": 0}
    note = {"tcg_mp_listing_id": 999, "tcg_mp_card_id": 200}
    sold_index = _build_sold_index([{
        "order_id": "0002", "status": "In Transit",
        "items": [{"product_id": 200, "foil": 0, "name": "Llanowar Elves"}],
    }])
    c = _match_candidate(
        item, note, active_listing_ids=set(), active_product_foil={(200, 0)},
        sold_index=sold_index, product_candidate_count=1,
    )
    assert c is not None and c["confidence"] == "high"
    assert c["match_basis"] == "product_unique"
    assert c["assessment"].startswith("HIGH")


def test__match_candidate_not_listed_but_sold_is_listing_gone():
    item = {"emid": "3", "inventory_id": "i3", "note_id": "n3", "foil": 0}
    note = {"tcg_mp_listing_id": 7, "tcg_mp_card_id": 100}
    sold_index = _build_sold_index([{
        "order_id": "0003", "status": "Completed",
        "items": [{"product_id": 100, "listing_id": 7, "foil": 0, "name": "X"}],
    }])
    # Mapped listing 7 is NOT active and the product sold → listing_gone (high).
    c = _match_candidate(item, note, active_listing_ids=set(),
                         active_product_foil=set(), sold_index=sold_index)
    assert c is not None
    assert c["detection"] == "listing_gone" and c["confidence"] == "high"


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
    # approval column defaults to "no" and leads the schema
    assert row["approved"] == "no"
    assert CSV_FIELDS[0] == "approved" and CSV_FIELDS[1] == "card_name"
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
    assert lines[0].split(",")[0] == "approved"


def test__owned_counts_groups_by_emid_and_foil():
    inv = [
        {"emid": "100", "foil": 0, "note_id": "n1"},
        {"emid": "100", "foil": 0, "note_id": "n2"},              # 2 listed non-foil copies
        {"emid": "100", "foil": 0},                               # collection-only; not counted
        {"emid": "100", "foil": 1, "note_id": "n3"},              # 1 listed foil copy
        {"emid": "200", "foil": 0, "note_id": "n4"},
        {"not": "a card"},
    ]
    counts = _owned_counts(inv)
    assert counts[("100", 0)] == 2
    assert counts[("100", 1)] == 1
    assert counts[("200", 0)] == 1


class _FakeInventory:
    def __init__(self, copies):
        self._copies = copies
    def search_card(self, emid, tradable_only=1):
        return self._copies


class _FakeNotes:
    def __init__(self, notes):
        self.notes = notes

    def get_note(self, note_id):
        return self.notes[note_id]


class _FakePublish:
    def __init__(self):
        self.calls = []
    def edit_listing(self, **kw):
        self.calls.append(("edit", kw))
    def remove_listings(self, ids):
        self.calls.append(("remove", ids))


def test__reconcile_listing_edits_to_remaining_when_copies_left():
    # one non-foil copy still held → set listing quantity to 1 (not delist)
    pub = _FakePublish()
    inv = _FakeInventory([{"foil": 0, "note_id": "n1"}])
    res = _reconcile_listing(pub, inv, emid="100", foil=0, listing_id=7,
                             price=4.20, condition="NM")
    assert res == "qty->1"
    assert pub.calls[0][0] == "edit" and pub.calls[0][1]["quantity"] == 1
    assert pub.calls[0][1]["listing_id"] == 7


def test__reconcile_listing_delists_when_none_left():
    pub = _FakePublish()
    inv = _FakeInventory([])           # no copies remain
    res = _reconcile_listing(pub, inv, emid="100", foil=0, listing_id=7,
                             price=4.20, condition="NM")
    assert res == "delisted(0 left)"
    assert pub.calls[0] == ("remove", [7])


def test__reconcile_listing_counts_only_matching_foil():
    pub = _FakePublish()
    inv = _FakeInventory([
        {"foil": 1, "note_id": "n1"},
        {"foil": 1, "note_id": "n2"},
        {"foil": 0, "note_id": "n3"},
    ])  # 2 foil, 1 non-foil
    res = _reconcile_listing(pub, inv, emid="100", foil=1, listing_id=9,
                             price=1.0, condition="NM")
    assert res == "qty->2"


def test__copy_has_listing_note_validates_note_metadata_when_service_available():
    notes = _FakeNotes({
        "n1": {"note": {"note": '{"tcg_mp_card_id": 787544}'}},
        "n2": {"note": {"note": '{"tcg_mp_card_id": 999999}'}},
    })
    assert _copy_has_listing_note({"note_id": "n1"}, notes, product_id=787544) is True
    assert _copy_has_listing_note({"note_id": "n2"}, notes, product_id=787544) is False
    assert _copy_has_listing_note({}, notes, product_id=787544) is False


def test__reconcile_listing_ignores_note_less_collection_copies():
    pub = _FakePublish()
    inv = _FakeInventory([
        {"foil": 0, "note_id": "n1"},
        {"foil": 0},  # collection-only: tradable in EchoMTG, not listed on TCGMP
        {"foil": 0, "note_id": "n2"},  # note exists but maps a different product
    ])
    notes = _FakeNotes({
        "n1": {"note": {"note": '{"tcg_mp_card_id": 787544}'}},
        "n2": {"note": {"note": '{"tcg_mp_card_id": 999999}'}},
    })

    res = _reconcile_listing(
        pub, inv, emid="100", foil=0, listing_id=7, price=4.20,
        condition="NM", notes_service=notes, product_id=787544,
    )

    assert res == "qty->1"
    assert pub.calls[0][1]["quantity"] == 1


def test__status_label_maps_codes():
    assert _status_label(3) == "Completed"
    assert _status_label("4") == "Cancelled"
    assert _status_label(8) == "Picked Up"
    # already-a-label passes through; unknown/blank handled
    assert _status_label("Completed") == "Completed"
    assert _status_label(9) == "In Transit"
    assert _status_label(None) == ""


def test__default_sold_statuses_exclude_pending_drop_off():
    labels = {s.label for s in DEFAULT_SOLD_STATUSES}
    assert EnumTcgOrderStatus.PENDING_DROP_OFF not in DEFAULT_SOLD_STATUSES
    assert EnumTcgOrderStatus.CANCELLED not in DEFAULT_SOLD_STATUSES
    assert "Pending Drop Off" not in labels
    assert "Cancelled" not in labels
    assert "In Transit" in labels
    assert _status_is_allowed(9, labels) is True
    assert _status_is_allowed(1, labels) is False
    assert _status_is_allowed("1", labels) is False
    assert _status_is_allowed("Pending Drop Off", labels) is False
    assert _status_is_allowed("Cancelled", labels) is False


class _FakeOrderPage:
    def __init__(self, data):
        self.data = data


class _FakeOrderService:
    def get_orders(self, **kwargs):
        return [_FakeOrderPage([{"order_id": "pending-detail"}])]

    def get_order_detail(self, order_id):
        return {
            "order_id": order_id,
            "status": EnumTcgOrderStatus.PENDING_DROP_OFF.code,
            "items": [{"product_id": 100, "listing_id": 7}],
        }


def test__gather_live_order_details_filters_pending_drop_off_detail():
    details = _gather_live_order_details(
        _FakeOrderService(),
        statuses=(EnumTcgOrderStatus.DROPPED,),
        last_x_days=60,
    )
    assert details == {}


def test__gather_es_order_details_filters_pending_drop_off(monkeypatch):
    docs = [
        {
            "external_id": "pending-label",
            "current_status": "Pending Drop Off",
            "last_raw_payload": {"order_id": "pending-label", "items": []},
        },
        {
            "external_id": "pending-code",
            "current_status": "Completed",
            "last_raw_payload": {"order_id": "pending-code", "status": 1, "items": []},
        },
        {
            "external_id": "dropped",
            "current_status": "Dropped Off",
            "last_raw_payload": {"order_id": "dropped", "status": 6, "items": []},
        },
    ]
    monkeypatch.setattr(radar_module, "get_index_data", lambda *args, **kwargs: docs)

    details = _gather_es_order_details({s.label for s in DEFAULT_SOLD_STATUSES})

    assert set(details) == {"dropped"}


def test__apply_radar_approvals_dry_run(tmp_path):
    """Reads an edited CSV and previews only the approved rows — no API calls."""
    csv_path = tmp_path / "review.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerow({"approved": "yes", "card_name": "Sol Ring", "emid": "1",
                    "inventory_id": "i1", "listing_id": "7", "echo_foil": "0",
                    "acquired_price": "1.00", "sold_price": "4.00"})
        w.writerow({"approved": "no", "card_name": "Llanowar Elves", "emid": "2",
                    "inventory_id": "i2", "listing_id": "8"})
    summary = apply_radar_approvals(str(csv_path), dry_run=True)
    assert "1/1 approved" in summary and "dry run" in summary.lower()


def test__apply_radar_approvals_no_approved_rows(tmp_path):
    csv_path = tmp_path / "none.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerow({"approved": "no", "card_name": "X", "emid": "1", "inventory_id": "i1"})
    summary = apply_radar_approvals(str(csv_path), dry_run=True)
    assert "no approved rows" in summary


@pytest.mark.skip(reason="Destructive — marks sold, removes inventory, and delists approved rows")
def test__apply_radar_approvals_apply():
    apply_radar_approvals("sold_inventory_radar-EDITED.csv", dry_run=False)


