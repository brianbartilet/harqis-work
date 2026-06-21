"""
workflows/purchases/tasks/sold_inventory_radar.py

Sold-inventory radar — surface (and optionally clean up) EchoMTG inventory items
that are almost certainly already SOLD on The TCG Marketplace yet are still in
the inventory and still actively listed: the exact state that produces an order
you cannot fulfil.

Background — the failure mode this guards against (documented in
``tcg_mp_selling.py`` around the ``update_tcg_listings_prices`` worker):

  1. A card sells on TCG MP.
  2. The EchoMTG inventory is not updated (the copy is never marked sold/removed).
  3. A new copy of the same card is later added, OR the price-update beat resets
     the note's ``tcg_mp_listing_id`` to 0 and ``generate_tcg_listings`` re-creates
     the listing — re-listing a card you no longer physically hold.
  => A buyer can order a card you can't ship.

This task cross-references terminal/sold TCG orders (Completed, Picked Up,
Cancelled, Not Received) against the current EchoMTG tradable inventory and the
current active TCG listings, using the per-item EchoMTG note (written by
``generate_tcg_mappings``) as the join key:

    echo note.tcg_mp_listing_id  ─┐
    echo note.tcg_mp_card_id      ├─►  matched to a sold order's line items
    echo item.foil                ─┘    AND the still-active TCG listings

Order history uses a HYBRID source: the ES audit index maintained by
``generate_audit_for_tcg_orders`` (cheap, historical) UNION a fresh live poll of
the order API (covers the current window + statuses the audit may not hold yet).

Output (ALWAYS produced, even when applying):
  - one ES doc per candidate in ``tcg-mp-sold-radar``
  - a Markdown review file under ``<repo>/logs/purchases/``
  - a HUD feed line (``@feed``) summarising the run

When ``dry_run`` is False (the default), each qualifying candidate is also acted
on — marked sold in EchoMTG earnings, removed from the EchoMTG inventory, and
delisted on TCG MP — and every acted item is included in the review list so you
can still physically verify afterwards.

This task only READS the live selling pipeline's artifacts (the notes) and acts
on inventory/listings; it does not modify the ``generate_tcg_*`` logic.
"""

import csv
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result, post, get_index_data
from core.utilities.logging.custom_logger import create_logger

from apps.apps_config import CONFIG_MANAGER
from apps.desktop.helpers.feed import feed

from apps.echo_mtg.references.web.api.inventory import ApiServiceEchoMTGInventory
from apps.echo_mtg.references.web.api.notes import ApiServiceEchoMTGNotes
from apps.echo_mtg.references.web.api.earnings import ApiServiceEchoMTGEarnings
from apps.tcg_mp.references.web.api.order import ApiServiceTcgMpOrder
from apps.tcg_mp.references.web.api.view import ApiServiceTcgMpUserView
from apps.tcg_mp.references.web.api.publish import ApiServiceTcgMpPublish
from apps.tcg_mp.references.dto.order import EnumTcgOrderStatus

_log = create_logger("purchases.sold_inventory_radar")

REPO_ROOT = Path(__file__).resolve().parents[3]

RADAR_INDEX = "tcg-mp-sold-radar"
AUDIT_CURRENT_INDEX = "tcg-mp-audit-current"

# Generated CSV review lists land here. The folder is tracked in git (via its
# .gitignore) but all generated contents are ignored — see results/.gitignore.
RESULTS_DIR = "results"

# Flat column order for the CSV review list — EchoMTG side, the note (join key),
# the live TCG listing, and the sold-order evidence, all on one row per card.
CSV_FIELDS = [
    "card_name", "confidence", "assessment", "recommended_action", "applied", "action_results",
    # ── EchoMTG side ──
    "emid", "inventory_id", "note_id", "echo_foil",
    "echo_set", "echo_condition", "echo_acquired_price", "echo_date_acquired",
    "echo_current_price", "echo_price_change",
    # ── EchoMTG note (join key written by generate_tcg_mappings) ──
    "note_scryfall_guid", "note_tcgplayer_id", "note_tcg_mp_card_id",
    "note_tcg_mp_listing_id", "note_tcg_mp_selling_price", "note_tcg_price",
    "note_last_updated",
    # ── TCG MP live listing (the still-active, erroneous listing) ──
    "listing_id", "listing_product_id", "listing_name", "listing_set",
    "listing_price", "listing_quantity", "listing_condition", "listing_foil",
    # ── TCG MP sold-order evidence ──
    "sold_in_orders",
    # ── values used by the mark-sold action ──
    "acquired_price", "sold_price",
]

# Order statuses treated as evidence the physical card left your hands. The
# operator reviews all of these manually today (completed + cancelled etc.).
DEFAULT_SOLD_STATUSES = (
    EnumTcgOrderStatus.COMPLETED,
    EnumTcgOrderStatus.PICKED_UP,
    EnumTcgOrderStatus.CANCELLED,
    EnumTcgOrderStatus.NOT_RECEIVED,
)

_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


# ── pure helpers (unit-tested) ────────────────────────────────────────────────

def _norm_foil(value) -> int:
    """Normalise EchoMTG/TCG foil flags (0/1/'0'/'1'/'foil'/'') to int 0|1."""
    if value in (1, "1", True, "foil", "Foil", "FOIL"):
        return 1
    return 0


def _to_int(value) -> Optional[int]:
    """Best-effort int coercion; None when not convertible."""
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _first(d: dict, *keys, default=None):
    """Return the first present, non-None value among ``keys`` in ``d``."""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _parse_note(note_response) -> Optional[dict]:
    """Extract the JSON note dict written by generate_tcg_mappings, or None.

    EchoMTG get_note returns ``{'status': 'error', 'note': 'not found'}`` when no
    note exists, and ``{'note': {'note': '<json string>'}}`` when it does.
    """
    if not isinstance(note_response, dict):
        return None
    note_field = note_response.get("note")
    if not isinstance(note_field, dict):
        return None
    raw = note_field.get("note")
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _extract_order_items(order_detail: dict) -> list[dict]:
    """Normalise a TCG MP order-detail payload into a flat list of sold line items.

    Defensive about key names: the order-detail item shape is not formally typed
    (mirrors DtoListingItem — product_id/listing_id/crd_foil/crd_name/qty/price).
    """
    if not isinstance(order_detail, dict):
        return []
    raw_items = order_detail.get("items")
    if not isinstance(raw_items, list):
        return []

    order_id = _first(order_detail, "order_id", "id", default="")
    status = _first(order_detail, "status", "current_status")

    items = []
    for it in raw_items:
        if not isinstance(it, dict):
            continue
        items.append({
            "order_id": order_id,
            "status": status,
            "product_id": _to_int(_first(it, "product_id", "crd_product_id", "productId")),
            "listing_id": _to_int(_first(it, "listing_id", "crd_listing_id", "listingId")),
            "foil": _norm_foil(_first(it, "crd_foil", "foil", default=0)),
            "name": _first(it, "crd_name", "name", "card_name", default=""),
            "qty": _to_int(_first(it, "qty", "quantity", default=1)) or 1,
            "price": _first(it, "price", "crd_price", "unit_price"),
        })
    return items


def _build_sold_index(order_details: list[dict]) -> dict:
    """Index sold line items by listing_id and by (product_id, foil).

    Returns ``{"by_listing": {lid: [occ]}, "by_product": {(pid, foil): [occ]}}``
    where each occurrence carries the order id/status/name/price for the report.
    """
    by_listing: dict = {}
    by_product: dict = {}
    for detail in order_details:
        for item in _extract_order_items(detail):
            occ = {
                "order_id": item["order_id"],
                "status": item["status"],
                "name": item["name"],
                "price": item["price"],
                "qty": item["qty"],
                "foil": item["foil"],
            }
            if item["listing_id"]:
                by_listing.setdefault(item["listing_id"], []).append(occ)
            if item["product_id"] is not None:
                by_product.setdefault((item["product_id"], item["foil"]), []).append(occ)
    return {"by_listing": by_listing, "by_product": by_product}


def _match_candidate(item: dict, note: dict, active_listing_ids: set,
                     active_product_foil: set, sold_index: dict) -> Optional[dict]:
    """Return a radar candidate for one inventory item, or None.

    A candidate is an inventory item that is STILL actively listed AND maps to a
    card that appears in a sold order. Confidence:
      - high   : the note's exact listing_id was sold and is still listed
      - medium : the note's product_id + foil was sold and is still listed
    """
    listing_id = _to_int(note.get("tcg_mp_listing_id"))
    product_id = _to_int(note.get("tcg_mp_card_id"))
    foil = _norm_foil(item.get("foil"))

    still_listed = (
        (listing_id is not None and listing_id in active_listing_ids)
        or (product_id is not None and (product_id, foil) in active_product_foil)
    )
    if not still_listed:
        return None

    matched_orders = []
    confidence = None

    if listing_id and listing_id in sold_index["by_listing"]:
        confidence = "high"
        matched_orders = sold_index["by_listing"][listing_id]
    elif product_id is not None and (product_id, foil) in sold_index["by_product"]:
        confidence = "medium"
        matched_orders = sold_index["by_product"][(product_id, foil)]

    if confidence is None:
        return None

    name = matched_orders[0].get("name") if matched_orders else ""
    sold_price = matched_orders[0].get("price") if matched_orders else None

    foil_label = "foil" if foil else "non-foil"
    orders_desc = "; ".join(
        f"{o.get('order_id')} ({o.get('status')})" for o in matched_orders[:5]
    ) or "an order"
    n_orders = len({o.get("order_id") for o in matched_orders})
    if confidence == "high":
        assessment = (
            f"HIGH: this card's exact TCG listing {listing_id} was sold in "
            f"{n_orders} order(s) [{orders_desc}], yet the listing is STILL active on "
            f"TCG MP and the card is STILL in EchoMTG inventory — the physical copy "
            f"was almost certainly already sold. Recommend: mark sold + remove from "
            f"inventory + delist."
        )
    else:  # medium
        assessment = (
            f"MEDIUM: TCG product {product_id} ({foil_label}) was sold in "
            f"{n_orders} order(s) [{orders_desc}] and a matching card is still "
            f"actively listed (listing {listing_id or 'n/a'}) and in inventory. "
            f"Likely a duplicate re-list or oversell — physically verify you still "
            f"hold a copy before removing."
        )

    return {
        "emid": item.get("emid"),
        "inventory_id": item.get("inventory_id"),
        "note_id": item.get("note_id"),
        "foil": foil,
        "card_name": name or item.get("name") or "",
        "tcg_mp_listing_id": listing_id,
        "tcg_mp_card_id": product_id,
        "scryfall_guid": note.get("scryfall_guid"),
        "confidence": confidence,
        "assessment": assessment,
        "acquired_price": str(_first(item, "acquired_price", "price_acquired", default="0")),
        "sold_price": str(sold_price if sold_price is not None
                          else note.get("tcg_mp_selling_price") or "0"),
        # full occurrence detail (order_id/status/qty/price/foil) for the CSV
        "matched_orders": [dict(o) for o in matched_orders],
        # raw EchoMTG item + parsed note carried for CSV enrichment in the task
        "echo_item": dict(item),
        "note": dict(note),
    }


def _lattr(listing, *names, default=""):
    """Read a field from a DtoListingItem (object) or a plain dict, with fallbacks."""
    for n in names:
        if isinstance(listing, dict):
            if listing.get(n) not in (None, ""):
                return listing[n]
        else:
            v = getattr(listing, n, None)
            if v not in (None, ""):
                return v
    return default


def _candidate_to_row(c: dict) -> dict:
    """Flatten a candidate (EchoMTG item + note + live listing + sold orders) into
    one CSV row keyed by CSV_FIELDS."""
    item = c.get("echo_item") or {}
    note = c.get("note") or {}
    listing = c.get("listing")
    orders = "; ".join(
        f"{o.get('order_id')}({o.get('status')},qty={o.get('qty')},price={o.get('price')})"
        for o in c.get("matched_orders", [])
    )
    actions = c.get("actions") or {}
    row = {
        "card_name": c.get("card_name", ""),
        "confidence": c.get("confidence", ""),
        "assessment": c.get("assessment", ""),
        "recommended_action": "mark_sold + remove_inventory + delist",
        "applied": c.get("applied", ""),
        "action_results": "; ".join(f"{k}:{v}" for k, v in actions.items()),
        # EchoMTG side
        "emid": c.get("emid", ""),
        "inventory_id": c.get("inventory_id", ""),
        "note_id": c.get("note_id", ""),
        "echo_foil": c.get("foil", ""),
        "echo_set": _first(item, "set", "edition", "expansion", "set_name", "setname", default=""),
        "echo_condition": _first(item, "condition", "grade", "crd_condition", default=""),
        "echo_acquired_price": _first(item, "acquired_price", "price_acquired", default=""),
        "echo_date_acquired": _first(item, "date_acquired", default=""),
        "echo_current_price": _first(item, "price", "market_price", "current_price", "tcg_mid", default=""),
        "echo_price_change": _first(item, "price_change", default=""),
        # EchoMTG note (join key)
        "note_scryfall_guid": note.get("scryfall_guid", ""),
        "note_tcgplayer_id": note.get("tcgplayer_id", ""),
        "note_tcg_mp_card_id": note.get("tcg_mp_card_id", ""),
        "note_tcg_mp_listing_id": note.get("tcg_mp_listing_id", ""),
        "note_tcg_mp_selling_price": note.get("tcg_mp_selling_price", ""),
        "note_tcg_price": note.get("tcg_price", ""),
        "note_last_updated": note.get("last_updated", ""),
        # TCG MP live listing
        "listing_id": _lattr(listing, "listing_id") if listing is not None else "",
        "listing_product_id": _lattr(listing, "product_id") if listing is not None else "",
        "listing_name": _lattr(listing, "name") if listing is not None else "",
        "listing_set": _lattr(listing, "setname", "crd_setcode") if listing is not None else "",
        "listing_price": _lattr(listing, "price") if listing is not None else "",
        "listing_quantity": _lattr(listing, "quantity") if listing is not None else "",
        "listing_condition": _lattr(listing, "crd_condition") if listing is not None else "",
        "listing_foil": _lattr(listing, "crd_foil") if listing is not None else "",
        # sold-order evidence
        "sold_in_orders": orders,
        # mark-sold inputs
        "acquired_price": c.get("acquired_price", ""),
        "sold_price": c.get("sold_price", ""),
    }
    return row


def _write_csv(path: Path, candidates: list[dict]) -> None:
    """Write the review list of candidates to a CSV at `path` (header always written)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for c in candidates:
            writer.writerow(_candidate_to_row(c))


# ── order gathering (hybrid: live poll + ES audit) ────────────────────────────

def _gather_live_order_details(service: ApiServiceTcgMpOrder, statuses, last_x_days: int) -> dict:
    """Live-poll terminal orders and fetch each order's detail. Keyed by order_id."""
    today = datetime.today().date()
    date_from = (today - timedelta(days=last_x_days)).isoformat()
    date_to = today.isoformat()

    details: dict = {}
    for status in statuses:
        try:
            pages = service.get_orders(by_status=status,
                                       date_range_from=date_from, date_range_to=date_to)
        except Exception as exc:  # noqa: BLE001 - one status failing must not abort the radar
            _log.warning("radar: get_orders failed for %s (%s)", status.label, exc)
            continue
        summaries = [o for page in (pages or []) if page for o in (page.data or [])]
        for summary in summaries:
            order_id = summary.get("order_id") if isinstance(summary, dict) else None
            if not order_id or order_id in details:
                continue
            try:
                detail = service.get_order_detail(order_id)
                if isinstance(detail, dict):
                    detail.setdefault("order_id", order_id)
                    details[order_id] = detail
            except Exception as exc:  # noqa: BLE001
                _log.warning("radar: get_order_detail failed for %s (%s)", order_id, exc)
    return details


def _gather_es_order_details(status_labels: set) -> dict:
    """Pull stored order-detail payloads from the audit current index. Keyed by order_id."""
    details: dict = {}
    try:
        docs = get_index_data(AUDIT_CURRENT_INDEX, type_hook=dict, fetch_docs=10000)
    except Exception as exc:  # noqa: BLE001 - ES optional; live poll still works
        _log.warning("radar: could not read %s (%s)", AUDIT_CURRENT_INDEX, exc)
        return details
    for doc in docs or []:
        if status_labels and doc.get("current_status") not in status_labels:
            continue
        payload = doc.get("last_raw_payload")
        if isinstance(payload, dict):
            order_id = payload.get("order_id") or doc.get("external_id")
            if order_id and order_id not in details:
                payload.setdefault("order_id", order_id)
                details[order_id] = payload
    return details


# ── the task ──────────────────────────────────────────────────────────────────

@log_result()
@feed()
@SPROUT.task()
def radar_sold_inventory(dry_run: bool = False, last_x_days: int = 60,
                         source: str = "hybrid", limit: Optional[int] = None,
                         **kwargs) -> str:
    """Find EchoMTG items already sold on TCG MP but still listed, and clean them up.

    Args:
        dry_run: When True, only build the review list (no mutations). Default
                 False — the run marks sold + removes inventory + delists.
        last_x_days: Window for the live order poll (Completed/Cancelled etc.).
        source: 'hybrid' (ES audit + live poll), 'live', or 'es'.
        limit: Cap the number of inventory items scanned (testing).
        cfg_id__tcg_mp / cfg_id__echo_mtg / cfg_id__echo_mtg_fe: config keys.
        apply_actions: which of 'mark_sold','remove_inventory','delist' to perform
                       (default all three). Ignored when dry_run is True.
        min_confidence: 'low'|'medium'|'high' threshold to act on (default 'low').
        sold_statuses: optional iterable of EnumTcgOrderStatus to override defaults.

    Returns:
        A one-line summary string (also pushed to the HUD feed).
    """
    cfg_id__tcg_mp = kwargs.get("cfg_id__tcg_mp", "TCG_MP")
    cfg_id__echo_mtg = kwargs.get("cfg_id__echo_mtg", "ECHO_MTG")
    apply_actions = set(kwargs.get("apply_actions",
                                   ("mark_sold", "remove_inventory", "delist")))
    min_conf = kwargs.get("min_confidence", "low")
    statuses = tuple(kwargs.get("sold_statuses", DEFAULT_SOLD_STATUSES))
    status_labels = {s.label for s in statuses}

    cfg__tcg_mp = CONFIG_MANAGER.get(cfg_id__tcg_mp)
    cfg__echo_mtg = CONFIG_MANAGER.get(cfg_id__echo_mtg)

    order_service = ApiServiceTcgMpOrder(cfg__tcg_mp)
    view_service = ApiServiceTcgMpUserView(cfg__tcg_mp)
    publish_service = ApiServiceTcgMpPublish(cfg__tcg_mp)
    inventory_service = ApiServiceEchoMTGInventory(cfg__echo_mtg)
    notes_service = ApiServiceEchoMTGNotes(cfg__echo_mtg)
    earnings_service = ApiServiceEchoMTGEarnings(cfg__echo_mtg)

    # ── 1. gather sold order history (hybrid) ────────────────────────────────
    details: dict = {}
    if source in ("es", "hybrid"):
        details.update(_gather_es_order_details(status_labels))
    if source in ("live", "hybrid"):
        # live poll wins on key collisions (fresher) — applied last
        details.update(_gather_live_order_details(order_service, statuses, last_x_days))
    sold_index = _build_sold_index(list(details.values()))
    _log.info("radar: %d sold order(s); %d listing key(s), %d product key(s)",
              len(details), len(sold_index["by_listing"]), len(sold_index["by_product"]))

    # ── 2. current active TCG listings ───────────────────────────────────────
    listings = view_service.get_listings() or []
    active_listing_ids = {l.listing_id for l in listings if getattr(l, "listing_id", None)}
    active_product_foil = {
        (l.product_id, _norm_foil(l.crd_foil))
        for l in listings if getattr(l, "product_id", None) is not None
    }
    listing_by_id = {l.listing_id: l for l in listings if getattr(l, "listing_id", None)}
    listing_by_pf = {
        (l.product_id, _norm_foil(l.crd_foil)): l
        for l in listings if getattr(l, "product_id", None) is not None
    }

    # ── 3. inventory + notes → candidates ────────────────────────────────────
    inventory = inventory_service.get_collection(tradable_only=1) or []
    if not isinstance(inventory, list):
        _log.warning("radar: echo inventory did not return a list; aborting")
        return "Sold-radar: echo inventory unavailable"
    if limit is not None:
        inventory = inventory[:limit]

    candidates: list[dict] = []
    for item in inventory:
        note_id = item.get("note_id")
        if not note_id:
            continue
        try:
            note = _parse_note(notes_service.get_note(note_id))
        except Exception as exc:  # noqa: BLE001
            _log.warning("radar: get_note failed for %s (%s)", note_id, exc)
            continue
        if not note:
            continue
        candidate = _match_candidate(item, note, active_listing_ids,
                                     active_product_foil, sold_index)
        if candidate:
            # attach the still-active TCG listing (the erroneous one) for the CSV
            candidate["listing"] = (
                listing_by_id.get(candidate.get("tcg_mp_listing_id"))
                or listing_by_pf.get((candidate.get("tcg_mp_card_id"), candidate.get("foil")))
            )
            candidates.append(candidate)

    _log.info("radar: %d candidate(s) from %d inventory item(s)",
              len(candidates), len(inventory))

    # ── 4. act (unless dry run) ──────────────────────────────────────────────
    threshold = _CONFIDENCE_RANK.get(min_conf, 0)
    acted = 0
    for c in candidates:
        if dry_run or _CONFIDENCE_RANK.get(c["confidence"], 0) < threshold:
            continue
        actions: dict = {}
        if "mark_sold" in apply_actions:
            try:
                earnings_service.add_sale(c["emid"], c["acquired_price"],
                                          c["sold_price"], foil=c["foil"])
                actions["mark_sold"] = "ok"
            except Exception as exc:  # noqa: BLE001
                actions["mark_sold"] = f"error:{exc}"
        if "remove_inventory" in apply_actions:
            try:
                inventory_service.remove_item(c["inventory_id"])
                actions["remove_inventory"] = "ok"
            except Exception as exc:  # noqa: BLE001
                actions["remove_inventory"] = f"error:{exc}"
        if "delist" in apply_actions and c.get("tcg_mp_listing_id"):
            try:
                publish_service.remove_listings([c["tcg_mp_listing_id"]])
                actions["delist"] = "ok"
            except Exception as exc:  # noqa: BLE001
                actions["delist"] = f"error:{exc}"
        c["actions"] = actions
        acted += 1

    # ── 5. always emit the review list (CSV file + ES) ───────────────────────
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    for c in candidates:
        c["applied"] = (not dry_run)

    out_file = REPO_ROOT / RESULTS_DIR / f"sold_inventory_radar-{run_id}.csv"
    _write_csv(out_file, candidates)

    for c in candidates:
        # one JSON-safe flat doc per candidate (same columns as the CSV)
        doc = {**_candidate_to_row(c), "run_id": run_id, "generated_at": stamp}
        try:
            post(json_dump=doc, index_name=RADAR_INDEX,
                 location_key=f"radar-{run_id}-{c.get('inventory_id')}",
                 use_interval_map=False)
        except Exception as exc:  # noqa: BLE001 - ES write must not break the run
            _log.warning("radar: ES write failed for %s (%s)", c.get("inventory_id"), exc)

    summary = (
        f"Sold-radar: {len(candidates)} candidate(s), "
        f"{'0 acted (dry run)' if dry_run else f'{acted} acted'} — review {out_file}"
    )
    _log.info(summary)
    return summary
