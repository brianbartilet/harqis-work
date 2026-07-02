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

This task cross-references sold/in-flight TCG orders — every status from drop-off
onward (Dropped Off, Arrived Branch, Shipped, Picked Up, Completed) plus the
terminal Cancelled / Not Received, i.e. anything that means the card has left your
hands; Pending Drop Off / Pending Payment are excluded as still-in-inventory —
against the current EchoMTG tradable inventory and the
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

import collections
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
    # ── REVIEW COLUMNS (lead) — set `approved` to yes on rows to action ──
    # `approved` defaults to "no"; edit the CSV, save it under results/, then the
    # skill applies only the approved rows. Sorted by listing_price (desc).
    "approved", "card_name", "listing_price", "assessment", "confidence", "sold_in_orders",
    # ── detection + action bookkeeping ──
    "detection", "recommended_action", "applied", "action_results",
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
    "listing_quantity", "listing_condition", "listing_foil",
    # copies of this card you still hold in EchoMTG (a listing maps to all of them)
    "echo_owned_count",
    # ── values used by the mark-sold action ──
    "acquired_price", "sold_price",
]

# Values in the `approved` column that mean "yes, perform the action on this row".
_APPROVED_TRUE = {"yes", "y", "true", "1", "x", "approved"}

# Order statuses treated as evidence the physical card left your hands. Drives BOTH
# the live order poll and the ES-audit filter (see status_labels in the task body).
#
# TCG MP lifecycle (apps/tcg_mp/references/dto/order.py): the card is still in your
# inventory only while the order is Pending Drop Off (1) or Pending Payment (11) —
# you haven't handed it over yet. Every state from Dropped Off (6) onward means the
# copy has physically left you: Dropped Off → Arrived Branch (7) → Shipped /
# "In Transit" (2) → Picked Up (8) / Completed (3). Cancelled (4) / Not Received (5)
# are terminal "gone" states too. So all of the below count as sold-and-gone;
# PENDING_DROP_OFF and PENDING_PAYMENT are deliberately excluded (still yours).
DEFAULT_SOLD_STATUSES = (
    EnumTcgOrderStatus.DROPPED,          # dropped at branch — no longer in hand
    EnumTcgOrderStatus.ARRIVED_BRANCH,   # at the branch — no longer in hand
    EnumTcgOrderStatus.SHIPPED,          # in transit to buyer — gone
    EnumTcgOrderStatus.PICKED_UP,
    EnumTcgOrderStatus.IN_TRANSIT,
    EnumTcgOrderStatus.COMPLETED,
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


def _to_float(value) -> float:
    """Best-effort float coercion; 0.0 when not convertible (for price sorting)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _owned_counts(inventory: list) -> dict:
    """Count EchoMTG tradable copies per (emid, foil). A TCG listing maps to ALL
    copies of the same card, so this count is the listing's intended quantity —
    selling one copy should set the listing to (count - sold), not delist it."""
    counts: dict = {}
    for it in inventory:
        if not isinstance(it, dict):
            continue
        emid = it.get("emid")
        if emid is None:
            continue
        key = (str(emid), _norm_foil(it.get("foil")))
        counts[key] = counts.get(key, 0) + 1
    return counts


def _status_label(value) -> str:
    """Map a TCG order status to its human label. The order-detail payload carries
    a numeric code (3, 4, …); the ES audit payload already stores the label string.
    Pass numbers through EnumTcgOrderStatus; keep label strings as-is."""
    code = _to_int(value)
    if code is not None:
        st = EnumTcgOrderStatus.from_code(code)
        return st.label if st else str(value)
    return str(value) if value is not None else ""


def _status_is_allowed(value, allowed_labels: set) -> bool:
    """Return True when a raw status value belongs to the allowed sold-status set."""
    if not allowed_labels:
        return True
    return _status_label(value) in allowed_labels


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
    status = _status_label(_first(order_detail, "status", "current_status"))

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
                "product_id": item["product_id"],
                "listing_id": item["listing_id"],
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


def _sold_quantity_budgets(sold_index: dict) -> dict:
    """Return mutable remaining sold quantities by exact listing and product/foil.

    A consolidated listing can map to multiple EchoMTG copies. Without a quantity
    budget, one sold line for qty=1 would match every copy stamped with the same
    listing id. Exact listing matches consume both the listing and product budgets
    so the same sold unit cannot be used again through product fallback.
    """
    by_listing: dict = {}
    by_product: dict = {}
    for listing_id, occurrences in sold_index.get("by_listing", {}).items():
        by_listing[listing_id] = sum(_to_int(o.get("qty")) or 1 for o in occurrences)
    for key, occurrences in sold_index.get("by_product", {}).items():
        by_product[key] = sum(_to_int(o.get("qty")) or 1 for o in occurrences)
    return {"by_listing": by_listing, "by_product": by_product}


def _claim_sold_unit(note: dict, foil, budgets: dict) -> bool:
    """Consume one sold quantity for this note/product if available."""
    listing_id = _to_int(note.get("tcg_mp_listing_id"))
    product_id = _to_int(note.get("tcg_mp_card_id"))
    product_key = (product_id, _norm_foil(foil)) if product_id is not None else None

    if listing_id and budgets["by_listing"].get(listing_id, 0) > 0:
        budgets["by_listing"][listing_id] -= 1
        if product_key and budgets["by_product"].get(product_key, 0) > 0:
            budgets["by_product"][product_key] -= 1
        return True

    if product_key and budgets["by_product"].get(product_key, 0) > 0:
        budgets["by_product"][product_key] -= 1
        return True

    return False


def _match_candidate(item: dict, note: dict, active_listing_ids: set,
                     active_product_foil: set, sold_index: dict,
                     owned_count: Optional[int] = None,
                     product_candidate_count: Optional[int] = None) -> Optional[dict]:
    """Return a radar candidate for one inventory item, or None.

    Two detections:
      • ``sold_still_listed`` — item is STILL actively listed AND its product/listing
        appears in a sold order (sold yet re-listed → can't fulfil). Confidence:
          high   = note's exact listing_id sold and still listed
          medium = note's product_id + foil sold and still listed
      • ``listing_gone`` — the note maps a ``tcg_mp_listing_id`` that is NO LONGER
        active on TCG MP (and no active listing exists for the product/foil): the
        listed copy sold or the listing was removed. Confidence:
          high   = listing gone AND product_id + foil appears in a sold order AND
                   exactly one EchoMTG candidate maps to that product/foil
          medium = product-only sold evidence exists but multiple EchoMTG candidates
                   map to that product/foil, so the exact physical copy is ambiguous
          low    = listing gone with no corroborating sold order (verify — the
                   listing may have sold OR just been removed/disabled)
    """
    listing_id = _to_int(note.get("tcg_mp_listing_id"))
    product_id = _to_int(note.get("tcg_mp_card_id"))
    foil = _norm_foil(item.get("foil"))

    still_listed = (
        (listing_id is not None and listing_id in active_listing_ids)
        or (product_id is not None and (product_id, foil) in active_product_foil)
    )
    sold_by_listing = bool(listing_id and listing_id in sold_index["by_listing"])
    sold_by_product = product_id is not None and (product_id, foil) in sold_index["by_product"]

    detection = confidence = None
    matched_orders: list = []
    recommended = "mark_sold + remove_inventory + delist"

    if still_listed:
        # Case A — sold but still listed (erroneous re-list)
        if sold_by_listing:
            detection, confidence = "sold_still_listed", "high"
            matched_orders = sold_index["by_listing"][listing_id]
        elif sold_by_product:
            detection, confidence = "sold_still_listed", "medium"
            matched_orders = sold_index["by_product"][(product_id, foil)]
        else:
            return None
        recommended = "mark_sold + remove_inventory + delist"
    else:
        # Case B — the mapped listing is no longer active (orphaned note)
        if not listing_id:
            return None  # nothing was ever listed → can't infer a sale
        detection = "listing_gone"
        recommended = "mark_sold + remove_inventory"   # listing already gone — no delist
        if sold_by_listing:
            confidence = "high"
            matched_orders = sold_index["by_listing"][listing_id]
        elif sold_by_product:
            confidence = "high" if (product_candidate_count or 0) == 1 else "medium"
            matched_orders = sold_index["by_product"][(product_id, foil)]
        else:
            confidence = "low"

    name = matched_orders[0].get("name") if matched_orders else ""
    sold_price = matched_orders[0].get("price") if matched_orders else None

    foil_label = "foil" if foil else "non-foil"
    orders_desc = "; ".join(
        f"{o.get('order_id')} ({o.get('status')})" for o in matched_orders[:5]
    ) or "—"
    n_orders = len({o.get("order_id") for o in matched_orders})

    if detection == "sold_still_listed" and confidence == "high":
        assessment = (
            f"HIGH: this card's exact TCG listing {listing_id} was sold in "
            f"{n_orders} order(s) [{orders_desc}], yet the listing is STILL active on "
            f"TCG MP and the card is STILL in EchoMTG inventory — the physical copy "
            f"was almost certainly already sold. Recommend: mark sold + remove + delist."
        )
    elif detection == "sold_still_listed":
        owned_txt = (f" You hold {owned_count} copy/copies in EchoMTG — approving this "
                     f"row removes one and sets the listing quantity to the remainder "
                     f"(delists only at 0)." if owned_count else "")
        assessment = (
            f"MEDIUM: TCG product {product_id} ({foil_label}) was sold in "
            f"{n_orders} order(s) [{orders_desc}] and a matching card is still "
            f"actively listed (listing {listing_id or 'n/a'}) and in inventory."
            f"{owned_txt} Verify you still physically hold a copy before removing."
        )
    elif detection == "listing_gone" and confidence == "high":
        assessment = (
            f"HIGH: the mapped TCG listing {listing_id} is NO LONGER active and "
            f"product {product_id} ({foil_label}) appears in {n_orders} sold order(s) "
            f"[{orders_desc}] with exactly one EchoMTG candidate for that product/foil "
            f"— the listed copy sold. Recommend: mark sold + remove from inventory "
            f"(listing already gone)."
        )
    elif detection == "listing_gone" and confidence == "medium":
        assessment = (
            f"MEDIUM: the mapped TCG listing {listing_id} is NO LONGER active and "
            f"product {product_id} ({foil_label}) appears in {n_orders} sold order(s) "
            f"[{orders_desc}], but {product_candidate_count or 'multiple'} EchoMTG "
            f"candidate copies map to that product/foil. Product-only evidence cannot "
            f"identify the exact physical copy; review before marking sold + removing."
        )
    else:  # listing_gone, low
        assessment = (
            f"LOW: the mapped TCG listing {listing_id} is no longer active, but no "
            f"matching sold order was found — it may have sold OR been removed/disabled. "
            f"Physically verify before marking sold + removing."
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
        "detection": detection,
        "confidence": confidence,
        "recommended_action": recommended,
        "assessment": assessment,
        "echo_owned_count": owned_count,
        "product_candidate_count": product_candidate_count,
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
        "approved": c.get("approved", "no"),
        "card_name": c.get("card_name", ""),
        "confidence": c.get("confidence", ""),
        "assessment": c.get("assessment", ""),
        "detection": c.get("detection", ""),
        "recommended_action": c.get("recommended_action", "mark_sold + remove_inventory + delist"),
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
        "echo_owned_count": c.get("echo_owned_count", ""),
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
    status_labels = {s.label for s in statuses}

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
                    raw_status = _first(detail, "status", "current_status", default=status.code)
                    if not _status_is_allowed(raw_status, status_labels):
                        continue
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
        payload = doc.get("last_raw_payload")
        raw_status = doc.get("current_status")
        if isinstance(payload, dict):
            raw_status = _first(payload, "status", "current_status", default=raw_status)
        if not _status_is_allowed(raw_status, status_labels):
            continue
        if isinstance(payload, dict):
            order_id = payload.get("order_id") or doc.get("external_id")
            if order_id and order_id not in details:
                payload.setdefault("order_id", order_id)
                details[order_id] = payload
    return details


def _reconcile_listing(publish_service, inventory_service, *, emid, foil,
                       listing_id, price, condition) -> str:
    """After a sold copy is removed, set the listing's quantity to the number of
    EchoMTG copies that REMAIN for this card (delist only if none remain).

    A listing maps to all copies of the same card, so when you own multiples and
    sell one, the right cleanup is to decrement the listing — not kill it. Mirrors
    update_tcg_listings_prices' quantity = len(matching inventory) logic. Returns a
    short result tag for the audit row.
    """
    try:
        copies = inventory_service.search_card(emid, tradable_only=1) or []
        remaining = sum(1 for c in copies if _norm_foil(c.get("foil")) == _norm_foil(foil))
    except Exception as exc:  # noqa: BLE001
        return f"error:count:{exc}"
    if remaining > 0:
        try:
            publish_service.edit_listing(listing_id=listing_id, price=price or 0,
                                         foil=_norm_foil(foil), quantity=remaining,
                                         condition=condition or "NM")
            return f"qty->{remaining}"
        except Exception as exc:  # noqa: BLE001
            return f"error:edit:{exc}"
    try:
        publish_service.remove_listings([listing_id])
        return "delisted(0 left)"
    except Exception as exc:  # noqa: BLE001
        return f"error:delist:{exc}"


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
        orphan_mode: how to treat notes whose mapped tcg_mp_listing_id is no longer
                     active ('listing_gone'): 'off' = ignore; 'corroborated' (default)
                     = include only when a sold order confirms it (high); 'all' =
                     include uncorroborated orphans (low) too. Skipped entirely if
                     TCG MP returns zero active listings (likely globally disabled).
        sold_statuses: optional iterable of EnumTcgOrderStatus to override defaults.

    Returns:
        A one-line summary string (also pushed to the HUD feed).
    """
    cfg_id__tcg_mp = kwargs.get("cfg_id__tcg_mp", "TCG_MP")
    cfg_id__echo_mtg = kwargs.get("cfg_id__echo_mtg", "ECHO_MTG")
    apply_actions = set(kwargs.get("apply_actions",
                                   ("mark_sold", "remove_inventory", "delist")))
    min_conf = kwargs.get("min_confidence", "low")
    # When True (default), the listing action sets the listing quantity to the number
    # of EchoMTG copies that remain (delist only at 0) instead of a blunt delist.
    reconcile_quantity = bool(kwargs.get("reconcile_quantity", True))
    # orphan_mode controls the 'listing_gone' detection (note maps a listing that is
    # no longer active): 'off' = skip it, 'corroborated' (default) = only when a sold
    # order corroborates (high), 'all' = include uncorroborated orphans (low) too.
    orphan_mode = kwargs.get("orphan_mode", "corroborated")
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
    # owned counts per (emid, foil) from the FULL inventory (before any --limit slice),
    # so a listing mapped to multiple copies reconciles to the right quantity.
    owned = _owned_counts(inventory)
    if limit is not None:
        inventory = inventory[:limit]

    parsed_inventory_notes: list[tuple[dict, dict]] = []
    product_candidate_counts: dict = collections.Counter()
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
        parsed_inventory_notes.append((item, note))
        product_id = _to_int(note.get("tcg_mp_card_id"))
        if product_id is not None:
            product_candidate_counts[(product_id, _norm_foil(item.get("foil")))] += 1

    candidates: list[dict] = []
    sold_budgets = _sold_quantity_budgets(sold_index)
    for item, note in parsed_inventory_notes:
        product_id = _to_int(note.get("tcg_mp_card_id"))
        foil = _norm_foil(item.get("foil"))
        owned_count = owned.get((str(item.get("emid")), foil))
        product_candidate_count = product_candidate_counts.get((product_id, foil), 0)
        candidate = _match_candidate(item, note, active_listing_ids,
                                     active_product_foil, sold_index,
                                     owned_count=owned_count,
                                     product_candidate_count=product_candidate_count)
        if candidate:
            if candidate.get("confidence") != "low" and not _claim_sold_unit(note, item.get("foil"), sold_budgets):
                continue
            # attach the still-active TCG listing (the erroneous one) for the CSV
            candidate["listing"] = (
                listing_by_id.get(candidate.get("tcg_mp_listing_id"))
                or listing_by_pf.get((candidate.get("tcg_mp_card_id"), candidate.get("foil")))
            )
            candidates.append(candidate)

    # ── 3b. orphan (listing_gone) handling ───────────────────────────────────
    # Guard: if NO active listings came back, "gone" is unreliable (listings may be
    # globally disabled via set_listing_status(0)), so drop all listing_gone here.
    if not active_listing_ids:
        before = len(candidates)
        candidates = [c for c in candidates if c.get("detection") != "listing_gone"]
        if before != len(candidates):
            _log.warning("radar: 0 active listings — dropping %d listing_gone candidate(s) "
                         "(listings may be disabled; gone-ness not trustworthy)",
                         before - len(candidates))
    if orphan_mode == "off":
        candidates = [c for c in candidates if c.get("detection") != "listing_gone"]
    elif orphan_mode == "corroborated":
        # keep listing_gone only when a sold order corroborates it (confidence high)
        candidates = [c for c in candidates
                      if c.get("detection") != "listing_gone" or c.get("confidence") == "high"]
    # orphan_mode == "all" → keep everything

    by_det = collections.Counter(c.get("detection") for c in candidates)
    _log.info("radar: %d candidate(s) from %d inventory item(s) (%s)",
              len(candidates), len(inventory), dict(by_det))

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
        # Listing action — only for still-active listings (sold_still_listed).
        # listing_gone rows have no live listing to touch.
        live_lid = _to_int(_lattr(c.get("listing"), "listing_id")) or c.get("tcg_mp_listing_id")
        if ("delist" in apply_actions and c.get("detection") == "sold_still_listed"
                and live_lid):
            if reconcile_quantity:
                actions["listing"] = _reconcile_listing(
                    publish_service, inventory_service,
                    emid=c["emid"], foil=c["foil"], listing_id=live_lid,
                    price=_to_float(_lattr(c.get("listing"), "price")) or _to_float(c.get("sold_price")),
                    condition=_lattr(c.get("listing"), "crd_condition", default="NM"))
            else:
                try:
                    publish_service.remove_listings([live_lid])
                    actions["listing"] = "delisted"
                except Exception as exc:  # noqa: BLE001
                    actions["listing"] = f"error:{exc}"
        c["actions"] = actions
        acted += 1

    # ── 5. always emit the review list (CSV file + ES) ───────────────────────
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    for c in candidates:
        c["applied"] = (not dry_run)
        c.setdefault("approved", "no")

    # Highest-value listings first so the operator reviews the costly cards up top.
    candidates.sort(key=lambda c: _to_float(_lattr(c.get("listing"), "price")), reverse=True)

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


@log_result()
@SPROUT.task()
def apply_radar_approvals(csv_path: str, dry_run: bool = False, **kwargs) -> str:
    """Perform the radar's recommended actions on the rows you APPROVED.

    Reads a review CSV you edited under results/ and acts ONLY on rows whose
    ``approved`` column is one of yes/y/true/1/x. For each approved row: mark the
    card sold in EchoMTG earnings, remove the EchoMTG inventory item, and delist
    it on TCG MP — using the ids stored in that row (emid, inventory_id,
    listing_id, foil, acquired/sold price). Writes an audit CSV
    (``sold_inventory_radar-applied-<ts>.csv``) with per-row results.

    Args:
        csv_path: Path to the approved CSV. Absolute, or a bare filename / relative
                  path which is resolved under results/.
        dry_run: If True, report what WOULD be actioned without calling any API.
        cfg_id__tcg_mp / cfg_id__echo_mtg: config keys (default 'TCG_MP'/'ECHO_MTG').
        apply_actions: subset of 'mark_sold','remove_inventory','delist' (default all).

    Returns:
        A one-line summary string.
    """
    cfg_id__tcg_mp = kwargs.get("cfg_id__tcg_mp", "TCG_MP")
    cfg_id__echo_mtg = kwargs.get("cfg_id__echo_mtg", "ECHO_MTG")
    apply_actions = set(kwargs.get("apply_actions",
                                   ("mark_sold", "remove_inventory", "delist")))
    # When True (default), set the listing quantity to the remaining EchoMTG copy
    # count after removal (delist only at 0) instead of a blunt delist.
    reconcile_quantity = bool(kwargs.get("reconcile_quantity", True))

    path = Path(csv_path)
    if not path.exists():
        path = REPO_ROOT / RESULTS_DIR / Path(csv_path).name
    if not path.exists():
        return f"Sold-radar apply: CSV not found: {csv_path}"

    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    approved = [r for r in rows
                if str(r.get("approved", "")).strip().lower() in _APPROVED_TRUE]
    if not approved:
        return f"Sold-radar apply: no approved rows (set approved=yes) in {path}"

    _log.info("radar apply: %d approved of %d row(s) from %s%s",
              len(approved), len(rows), path, " [DRY RUN]" if dry_run else "")

    earnings_service = inventory_service = publish_service = None
    if not dry_run:
        cfg__tcg_mp = CONFIG_MANAGER.get(cfg_id__tcg_mp)
        cfg__echo_mtg = CONFIG_MANAGER.get(cfg_id__echo_mtg)
        earnings_service = ApiServiceEchoMTGEarnings(cfg__echo_mtg)
        inventory_service = ApiServiceEchoMTGInventory(cfg__echo_mtg)
        publish_service = ApiServiceTcgMpPublish(cfg__tcg_mp)

    acted = 0
    for r in approved:
        emid = r.get("emid")
        inv = r.get("inventory_id")
        # Delist only a still-ACTIVE listing (the live `listing_id` column).
        # listing_gone rows have no live listing — don't try to delist a dead id.
        live_listing_id = _to_int(r.get("listing_id"))
        foil = _norm_foil(r.get("echo_foil"))
        # honour the per-row recommendation (orphans recommend no delist)
        row_actions = set(apply_actions)
        if "delist" not in (r.get("recommended_action") or ""):
            row_actions.discard("delist")

        if dry_run:
            r["action_results"] = "DRY RUN — would: " + ", ".join(sorted(row_actions))
            acted += 1
            continue

        actions: dict = {}
        if "mark_sold" in row_actions:
            try:
                earnings_service.add_sale(emid, r.get("acquired_price") or "0",
                                          r.get("sold_price") or "0", foil=foil)
                actions["mark_sold"] = "ok"
            except Exception as exc:  # noqa: BLE001
                actions["mark_sold"] = f"error:{exc}"
        if "remove_inventory" in row_actions:
            try:
                inventory_service.remove_item(inv)
                actions["remove_inventory"] = "ok"
            except Exception as exc:  # noqa: BLE001
                actions["remove_inventory"] = f"error:{exc}"
        if "delist" in row_actions and live_listing_id:
            if reconcile_quantity:
                actions["listing"] = _reconcile_listing(
                    publish_service, inventory_service,
                    emid=emid, foil=foil, listing_id=live_listing_id,
                    price=_to_float(r.get("listing_price")) or _to_float(r.get("sold_price")),
                    condition=(r.get("listing_condition") or "NM"))
            else:
                try:
                    publish_service.remove_listings([live_listing_id])
                    actions["listing"] = "delisted"
                except Exception as exc:  # noqa: BLE001
                    actions["listing"] = f"error:{exc}"
        r["action_results"] = "; ".join(f"{k}:{v}" for k, v in actions.items())
        r["applied"] = "true"
        acted += 1

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    audit = REPO_ROOT / RESULTS_DIR / f"sold_inventory_radar-applied-{run_id}.csv"
    audit.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else CSV_FIELDS
    with open(audit, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in approved:
            writer.writerow(r)

    summary = (
        f"Sold-radar apply: {acted}/{len(approved)} approved row(s) "
        f"{'previewed (dry run)' if dry_run else 'actioned'} — audit {audit}"
    )
    _log.info(summary)
    return summary


