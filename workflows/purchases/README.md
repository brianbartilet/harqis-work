# Purchases Workflow

## Description

- Automates the MTG card resale pipeline on The TCG Marketplace.
- Pipeline: Scryfall bulk download → card matching → listing generation → order audit → sold-inventory reconciliation → price/quantity updates.
- Uses multiprocessing (4 workers) for listing generation on Windows.
- A card is eligible for TCG Marketplace processing only when it comes from
  EchoMTG as `tradable_only=1` and has a valid JSON metadata note created by
  `generate_tcg_mappings`.

## Queue

Tasks run on the `tcg` queue.

## Scheduled Tasks

All jobs are registered in `WORKFLOW_PURCHASES` and run on `WorkflowQueue.TCG`.
Cron times are interpreted by the Celery Beat runtime timezone configured for the
deployment.

| Job key | Task | Schedule | Expiry | Purpose |
|---|---|---:|---:|---|
| `run-job--generate_tcg_mappings` | `tcg_mp_selling.generate_tcg_mappings` | Daily `00:00` | 8h | Build or refresh EchoMTG JSON metadata notes for tradable cards. |
| `run-job--generate_tcg_listings` | `tcg_mp_selling.generate_tcg_listings` | Daily `01:00` | 8h | Create missing TCG Marketplace listings from mapped EchoMTG notes, one per sellable variant. |
| `run-job--reconcile_then_update_tcg_listings` | `tcg_mp_selling.reconcile_then_update_tcg_listings` | Monday and Thursday `02:00` | 24h | Run sold-inventory radar first, then update live listing prices/quantities. |
| `run-job--download_scryfall_bulk_data` | `tcg_mp_selling.download_scryfall_bulk_data` | Days `1,15,25` at `22:00` | 24h | Refresh the local Scryfall bulk file used by mapping. |
| `run-job--generate_audit_for_tcg_orders` | `tcg_mp_selling.generate_audit_for_tcg_orders` | Every 4 hours at minute `0` | 4h | Poll TCG Marketplace orders and write current/audit status records to Elasticsearch. |

`radar_sold_inventory` and `update_tcg_listings_prices` are no longer scheduled
standalone. They run as the two ordered steps of
`reconcile_then_update_tcg_listings`. Both remain directly callable for manual
investigation and CSV-review use, including via `/radar-sold-inventory`.

The normal automated flow is:

```text
download_scryfall_bulk_data
  -> generate_tcg_mappings
  -> generate_tcg_listings
  -> generate_audit_for_tcg_orders keeps order state fresh
  -> reconcile_then_update_tcg_listings
       -> radar_sold_inventory
       -> update_tcg_listings_prices
```

Sequencing notes:

- `mappings` at `00:00` must precede `listings` at `01:00`; listings consume the
  notes that mappings writes.
- `reconcile_then_update_tcg_listings` runs radar to completion before
  `update_tcg_listings_prices` recomputes quantities. If radar fails, the update
  is skipped rather than re-inflating stale counts.
- The scheduled radar run uses `dry_run=False`, `min_confidence='high'`,
  `orphan_mode='corroborated'`, `last_x_days=60`, and `source='hybrid'`. It
  auto-actions only high-confidence candidates and writes the CSV audit output for
  review.
- Residual loop risk: between Mon/Thu chain runs, daily `generate_tcg_listings`
  can transiently re-list a freshly sold-but-unremoved card until the next
  radar/audit. Run radar or the approved-CSV apply flow more often for tighter
  control.
- `download_scryfall_bulk_data` runs at `22:00` on days `1,15,25` so it does not
  write the all-cards file while midnight mappings reads it.

## Task Files

| File | Tasks / Functions |
|------|-------------------|
| `tasks/tcg_mp_selling.py` | `generate_tcg_mappings`, `generate_tcg_listings`, `update_tcg_listings_prices`, `reconcile_then_update_tcg_listings` (chains radar → update), `download_scryfall_bulk_data`, `generate_audit_for_tcg_orders` |
| `tasks/sold_inventory_radar.py` | `radar_sold_inventory` (scan/clean) + `apply_radar_approvals` (approve-and-apply from CSV) |

## Shared Identity Rules

The selling workflow groups cards by a sellable variant:

```text
emid + foil + language + condition
```

This matters because a Japanese LP copy and an English NM copy of the same card
must not be collapsed into one listing.

The helper functions in `tcg_mp_selling.py` enforce this:

- `_norm_foil` normalizes EchoMTG and TCG foil values to `0` or `1`.
- `_normalize_language` maps EchoMTG language names and aliases to marketplace
  codes such as `EN`, `JP`, `KR`, and `CN`.
- `_language_value` reads `language` or `lang` from the EchoMTG record.
- `_condition_value` reads the EchoMTG condition and defaults to `NM`.
- `_variant_key` builds the strict grouping key for EchoMTG collection rows.
- `_same_variant` compares rows from different EchoMTG endpoints more tolerantly:
  foil must match, but missing language or condition on one side is treated as
  unknown rather than a mismatch.

## Sold-inventory radar (`radar_sold_inventory`)

**Goal:** surface (and optionally clean up) EchoMTG inventory items that are
already **sold** on TCG MP yet are still in the inventory **and** still actively
listed — the exact state that lets a buyer order a card you can't ship. Replaces
the manual monthly "review all completed/cancelled orders → remove cards in
EchoMTG by hand" process.

**Two detections** (the per-item EchoMTG note written by `generate_tcg_mappings` is
the join key — it carries `tcg_mp_listing_id`, `tcg_mp_card_id`, foil):

1. **`sold_still_listed`** — the item is **still actively listed** AND its
   product/listing appears in a sold order (sold yet re-listed → can't fulfil):
   - HIGH = note's exact `tcg_mp_listing_id` sold and still listed
   - MEDIUM = note's `tcg_mp_card_id` + foil sold and still listed
   - action: mark sold + remove inventory + **reconcile listing quantity**
     (a listing maps to every copy you own, so apply sets the listing's quantity to
     the EchoMTG copies that remain after removal, and **delists only when 0 remain** —
     it won't kill a listing you still have copies for). The CSV's `echo_owned_count`
     shows how many copies you hold.
2. **`listing_gone`** — the note maps a `tcg_mp_listing_id` that is **no longer
   active** on TCG MP (and no active listing exists for the product/foil): the listed
   copy sold or the listing was removed:
   - HIGH = listing gone **and** the product appears in a sold order
   - LOW = listing gone with no corroborating sold order (verify — may have sold OR
     just been removed/disabled)
   - action: mark sold + remove inventory (**no delist** — listing already gone)

`orphan_mode` controls detection #2: `off` | `corroborated` (default — HIGH only) |
`all` (include LOW orphans). It is skipped entirely if TCG MP returns **zero** active
listings (gone-ness is untrustworthy when listings are globally disabled).

**Order source (hybrid):** the ES audit index `tcg-mp-audit-current` (historical,
cheap) **UNION** a fresh live poll of the order API. Sold-evidence statuses are
dropped-or-later states: Dropped Off, Arrived Branch, Shipped, In Transit,
Picked Up, Completed, and Not Received. Pending Drop Off and Pending Payment are
excluded because the card is not physically handed off; Cancelled is audited but
is not part of the default sold-action evidence set.

**Apps chained:** `apps/tcg_mp` (orders, listings, delist), `apps/echo_mtg`
(inventory, notes, earnings mark-sold).

**Two-phase, operator-approved flow:**

1. **Scan** (`radar_sold_inventory(dry_run=True)`) → writes a **CSV** review list to
   `results/sold_inventory_radar-<ts>.csv`, **sorted by listing price (desc)**, lead
   columns `approved, card_name, listing_price, assessment, confidence, sold_in_orders`
   then the full EchoMTG + TCG MP detail and join keys. The `approved` column is `no`
   on every row. (Also one ES doc per row in `tcg-mp-sold-radar` + a `@feed` summary.)
2. **You edit the CSV** — set `approved` = `yes` on the rows to action, save under `results/`.
3. **Apply** (`apply_radar_approvals('<approved_csv>')`) → reads that CSV and, for the
   approved rows only, marks sold in EchoMTG earnings + removes inventory + reconciles
   or delists the TCG MP listing, writing an audit CSV
   `results/sold_inventory_radar-applied-<ts>.csv` with per-row `action_results`.

`assessment` explains, per row, why it was flagged (confidence, which listing/product
was sold, in which orders) and the recommended action. `results/` is tracked in git
but its contents are gitignored.

```python
from workflows.purchases.tasks.sold_inventory_radar import (
    radar_sold_inventory, apply_radar_approvals)

radar_sold_inventory(dry_run=True, limit=25)               # 1. scan → review CSV (no changes)
# 2. edit results/...csv: set approved=yes on chosen rows, save
apply_radar_approvals('sold_inventory_radar-<ts>.csv', dry_run=True)   # 3a. preview approved
apply_radar_approvals('sold_inventory_radar-<ts>.csv')                 # 3b. act on approved rows
```

> The scheduled chain runs `radar_sold_inventory` with high-confidence auto-apply
> enabled. Use `dry_run=True` plus `apply_radar_approvals(...)` for the fully
> operator-approved manual flow.

## Known issues in `tcg_mp_selling.py` — status

Found while building the radar; walked through and resolved/triaged:

1. **Quantity overcount → unfulfillable listings** — ✅ **hardened (code + data hygiene).**
   `update_tcg_listings_prices` sets a listing's `quantity` to the count of matching
   EchoMTG copies, which is **correct** *if inventory is accurate*. The bug was stale
   inventory (sold copies never removed). Now: (a) `reconcile_then_update_tcg_listings`
   runs `radar_sold_inventory` to completion **before** the quantity recompute, as a hard
   chain rather than a wall-clock gap; (b) the update worker **guards against quantity 0**
   (an empty/failed inventory search leaves the listing untouched instead of delisting);
   and (c) copy-counting now keys on the full variant (`emid+foil+language+condition`,
   tolerant across endpoints) so mixed condition/language copies don't over-count onto one
   listing. The radar's own apply still reconciles listing quantity to remaining copies.
2. **Sold → auto-relist loop** — ✅ **hardened (chain + variant consolidation).** When
   `edit_listing` returns `''` (listing gone) the worker resets `tcg_mp_listing_id = 0`
   (now across **all** copies of the variant) and `generate_tcg_listings` recreates it —
   **correct** when the listing was merely removed and you still own the card; **wrong**
   only when the card was sold and not removed. The radar's `listing_gone` detection finds
   exactly that and removes the orphan **before** recreation can run (same chain). Separately,
   `generate_tcg_listings` now creates **one listing per variant** at the live copy count and
   adopts an existing sibling listing instead of racing duplicates, so two unlisted copies of
   the same card become a single quantity-2 listing. Residual: between Mon/Thu chain runs, a
   freshly sold-but-unremoved card can be transiently re-listed by the daily
   `generate_tcg_listings` until the next radar/audit — run radar (or approve-and-apply) more
   often for tighter control.
3. **Audit didn't track Cancelled/Not Received** — ✅ **fixed.**
   `generate_audit_for_tcg_orders` now polls those two states (date-bounded).
4. **Misleading note-exists log + fragile shape** — ✅ **fixed.** `generate_tcg_mappings`
   now logs "No note yet … will create" in the not-found branch and handles both note
   shapes (`'not found'` string vs `{'note': …}` dict) defensively.
5. **`guid` may be `None` written into the note** — ✅ **fixed.** A guard skips note
   creation (with a warning) when no Scryfall GUID resolved, so no `scryfall_guid=None`
   note is ever persisted.
6. **Deprecated `logger.warn()`** — ✅ **fixed** → `.warning()`.
7. **`needs_lowest_seller` is never honoured** — *documented, behaviour unchanged.*
   `_update_pricing_calc` flags it for down/flat 7-day change but the worker prices off
   `base_price` either way (the lowest-seller lookup is not implemented). The code now
   says so explicitly. Effective pricing: down/flat → `base_price × multiplier`; upward
   → adjusted price × multiplier. Fetching + undercutting the marketplace's lowest
   seller (`ApiServiceTcgMpProducts.search_single_card_listings`) is a deliberate
   follow-up, not enabled here.
8. **`force_generate` disables listings without re-enabling** — ✅ **fixed.**
   `generate_tcg_mappings` now calls `set_listing_status(1)` at the end of a
   `force_generate` run, so a standalone force run no longer leaves the store off.

## App Dependencies

| App | Used For |
|-----|---------|
| `scryfall` | Bulk card data download and card metadata lookup |
| `tcg_mp` | Listing creation, price edits, order retrieval |
| `echo_mtg` | Owned inventory data (cards to list) |

## Helper Modules

| File | Description |
|------|-------------|
| `helpers/helper.py` | `load_scryfall_bulk_data()` — loads downloaded bulk JSON into memory |
| `helpers/constants.py` | `image_guid_pattern` — regex for TCG image GUID extraction |
| `helpers/mp_logging.py` | `log_mp_summary()` — summarizes multiprocessing worker results |

## Scheduled Job Details

### 1. Refresh Scryfall Bulk Data

`download_scryfall_bulk_data` runs on days `1,15,25` at `22:00`.

Procedure:

1. Load the `SCRYFALL` app config.
2. Instantiate `ApiServiceScryfallBulkData`.
3. Download the current Scryfall bulk file into the configured static data path.

`generate_tcg_mappings` uses the local Scryfall bulk file to validate that the
TCG Marketplace product it found is the same card EchoMTG knows about. The job
runs at `22:00` to avoid writing the bulk file while the midnight mapping job is
reading it.

### 2. Map EchoMTG Cards and Write Metadata Notes

`generate_tcg_mappings` runs daily at `00:00`.

Main inputs:

- EchoMTG inventory from `ApiServiceEchoMTGInventory.get_collection(tradable_only=1)`.
- EchoMTG card metadata from `ApiServiceEchoMTGCardItem.get_card_meta(emid)`.
- TCG Marketplace product search from `ApiServiceTcgMpProducts.search_card(name)`.
- Local Scryfall bulk data from `load_scryfall_bulk_data(...)`.
- EchoMTG notes from `ApiServiceEchoMTGNotes`.

Procedure:

1. Load app configs for TCG Marketplace, EchoMTG, EchoMTG frontend metadata, and
   Scryfall.
2. Pull EchoMTG collection rows with `tradable_only=1`.
3. Load the Scryfall bulk data file.
4. For each tradable EchoMTG card, fetch card metadata, search TCG Marketplace by
   clean card name, and validate the candidate through Scryfall `tcgplayer_id`.
5. If `force_generate=True`, delete the existing EchoMTG note first and disable
   marketplace listings while remapping.
6. If a valid existing TCG JSON note exists, keep it. Missing notes are created by
   default; pass `create_missing_notes=False` for an audit pass that skips missing
   or invalid notes.
7. Before writing a note, search EchoMTG for sibling copies of the same variant.
   If a sibling already has a `tcg_mp_listing_id`, inherit that listing id so the
   next listing job does not create a duplicate listing for the same variant.
8. Build `DtoNotesInformation` and write it as JSON into EchoMTG.

The note contains the workflow metadata used by later steps:

```json
{
  "scryfall_guid": "...",
  "tcgplayer_id": "...",
  "tcg_mp_card_id": 123456,
  "tcg_mp_listing_id": 0,
  "tcg_mp_selling_price": 0,
  "tcg_mp_smart_pricing": 0,
  "tcg_price": "...",
  "last_updated": "...",
  "function": "generate_tcg_mappings",
  "error": ""
}
```

`tcg_mp_listing_id = 0` means "mapped, but no active listing recorded yet".
A positive `tcg_mp_listing_id` means "this EchoMTG copy is tied to an existing
marketplace listing".

### 3. Create Missing TCG Marketplace Listings

`generate_tcg_listings` runs daily at `01:00`.

Main inputs:

- EchoMTG tradable inventory.
- EchoMTG JSON metadata notes.
- TCG Marketplace active listings.
- TCG Marketplace pending and handed-off order quantities.

Procedure:

1. Load TCG Marketplace and EchoMTG configs.
2. Fetch pending order reservations for Pending Drop Off and Pending Payment.
3. Fetch handed-off order quantities for dropped-or-later statuses over the
   configured date window.
4. Pull EchoMTG `get_collection(tradable_only=1)`.
5. Filter to cards needing a listing. A card qualifies only when it has an
   EchoMTG note, the note parses as valid JSON metadata, `tcg_mp_card_id > 0`,
   and `tcg_mp_listing_id == 0`.
6. Group cards by variant and dispatch one worker per variant group.
7. Resolve listing language and condition. Per-card EchoMTG language wins when
   present; the scheduled `language="EN"` kwarg is only the fallback.
8. Count listable live copies for the same variant and TCG product id.
9. Compute safe listing quantity by subtracting pending commitments and accounting
   for handed-off orders.
10. Create a TCG Marketplace listing or adopt/update an existing listing for the
    same product, foil, language, and condition.
11. Stamp every listable variant copy's EchoMTG note with the resolved
    `tcg_mp_listing_id`, selling price, and `function = "generate_tcg_listings"`.

At the end of this step, multiple listable copies of the same variant become one
listing with quantity `N`, not `N` separate listings.

### 4. Audit TCG Marketplace Orders

`generate_audit_for_tcg_orders` runs every 4 hours at minute `0`.

Main outputs:

- `tcg-mp-audit-current`: one current-status document per order.
- `tcg-mp-status-audit`: append-only status change records.

Procedure:

1. Load `TCG_MP` config and create `ApiServiceTcgMpOrder`.
2. Poll order summaries for Pending Drop Off, Arrived Branch, Dropped Off,
   Completed, Picked Up, Cancelled, Not Received, Shipped, and In Transit.
3. Fetch order detail for each order summary.
4. Compare the new status against `tcg-mp-audit-current`.
5. Write first-seen current-state docs, append status-change audit events, and
   update current-state docs when status changes.

The sold-inventory radar can use `tcg-mp-audit-current` as a cheap historical
source. It also does a live poll, but the audit job keeps older order evidence
available without repeatedly crawling every order.

### 5. Reconcile Sold Inventory, Then Update Listings

`reconcile_then_update_tcg_listings` runs Monday and Thursday at `02:00`.

Configured kwargs:

```python
radar_kwargs = {
    "dry_run": False,
    "min_confidence": "high",
    "orphan_mode": "corroborated",
    "last_x_days": 60,
    "source": "hybrid",
}
update_kwargs = {}
```

Procedure:

1. Merge top-level `cfg_id__*` kwargs into both radar and update kwargs.
2. Import `radar_sold_inventory` lazily.
3. Run `radar_sold_inventory(**radar_kwargs)`.
4. If radar raises an exception, log the failure and return
   `RADAR_FAILED_UPDATE_SKIPPED`.
5. Only after radar succeeds, run `update_tcg_listings_prices(**update_kwargs)`.
6. Return `SUCCESS`.

This is the safety chain. The updater can increase listing quantity from the
EchoMTG copy count, so radar must reconcile sold copies first.

### 5a. Sold-Inventory Radar

`radar_sold_inventory` is scheduled only through
`reconcile_then_update_tcg_listings`.

Manual review mode:

```text
radar_sold_inventory(dry_run=True)
```

Automated scheduled mode:

```text
radar_sold_inventory(
    dry_run=False,
    min_confidence="high",
    orphan_mode="corroborated",
    last_x_days=60,
    source="hybrid",
)
```

Action behavior:

1. If `dry_run=True`, no EchoMTG or TCG Marketplace mutation occurs.
2. If `dry_run=False`, only candidates at or above `min_confidence` are acted on.
3. `mark_sold` calls EchoMTG earnings `add_sale`.
4. `remove_inventory` calls EchoMTG inventory `remove_item`.
5. `delist` calls `_reconcile_listing` for still-active listings.
6. `_reconcile_listing` counts remaining EchoMTG copies that still have valid TCG
   metadata notes and match the product. It edits the listing quantity to that
   count, or removes the listing if the count is zero.
7. Every run writes a review CSV to `results/sold_inventory_radar-<timestamp>.csv`.
8. Candidate rows are also posted to Elasticsearch index `tcg-mp-sold-radar`.

Scheduled mode is intentionally stricter than manual mode: it uses
`min_confidence="high"` and `orphan_mode="corroborated"`, so ambiguous rows go to
CSV review instead of being actioned.

### 5b. Price and Quantity Update

`update_tcg_listings_prices` is not scheduled standalone. It runs after radar in
`reconcile_then_update_tcg_listings`.

Procedure:

1. Load EchoMTG and TCG Marketplace configs.
2. Fetch pending commitments and handed-off order quantities.
3. Pull EchoMTG `get_collection(tradable_only=1)`.
4. Keep only cards with note ids and group them by variant.
5. Pick one representative per variant, preferring a copy with a note.
6. Compute a base price from EchoMTG metadata: foil uses `foil_price`, non-foil
   uses `tcg_mid`.
7. Run `_update_pricing_calc`, then apply currency/market conversion and
   commission.
8. Resolve language and condition from EchoMTG.
9. Filter live copies to note-backed listable variants for the same TCG product.
10. Compute safe quantity by subtracting pending commitments and accounting for
    handed-off orders.
11. Choose a primary live listing, preferring the listing id stored in the note.
12. Remove/reset the listing when safe quantity is less than `1`; otherwise call
    `edit_listing(...)` with updated price, quantity, foil, language, condition,
    and listing id.
13. Remove duplicate live listings for the same variant.
14. Stamp every listable sibling note with the resolved listing id, selling price,
    and `function = "update_tcg_listings_prices"`.

Listings stay aligned with EchoMTG metadata, current pricing, active order
commitments, and the note-backed listable quantity.

## Manual Approval Flow

The manual radar workflow uses:

```text
radar_sold_inventory(dry_run=True)
apply_radar_approvals(csv_path, dry_run=True)
apply_radar_approvals(csv_path, dry_run=False)
```

Procedure:

1. Run the radar dry run.
2. Open the CSV in `results/`.
3. Set `approved=yes` only on rows to action.
4. Preview with `apply_radar_approvals(..., dry_run=True)`.
5. Apply with `dry_run=False`.

`apply_radar_approvals` acts only from the approved CSV rows, not a fresh scan.
It writes an audit CSV to `results/sold_inventory_radar-applied-<timestamp>.csv`.

## End-to-End Card Lifecycle

1. A card enters EchoMTG and is marked tradable.
2. At `00:00`, `generate_tcg_mappings` finds the EchoMTG frontend metadata,
   searches TCG Marketplace for a matching product, validates through Scryfall,
   and writes an EchoMTG note with `tcg_mp_card_id` and `tcg_mp_listing_id`.
3. At `01:00`, `generate_tcg_listings` finds mapped notes where
   `tcg_mp_listing_id == 0`, groups matching copies by variant, checks
   pending/open orders, creates or adopts a TCG Marketplace listing, and writes
   the listing id and selling price back into each listable copy's note.
4. Every 4 hours, `generate_audit_for_tcg_orders` polls marketplace orders and
   writes current status plus status changes into Elasticsearch.
5. On Monday and Thursday at `02:00`, radar gathers sold/order evidence from ES
   and live TCG Marketplace, compares it against EchoMTG inventory notes and
   active listings, applies high-confidence scheduled candidates, and writes CSV
   review output.
6. Only after radar succeeds, `update_tcg_listings_prices` recounts remaining
   listable EchoMTG copies, subtracts commitments, updates TCG Marketplace price
   and quantity, and stamps updated listing metadata back into EchoMTG notes.

## Running

```sh
# Start a worker for the tcg queue
celery -A workflows.config worker --loglevel=info -Q tcg

# Manually trigger listing generation
celery -A workflows.config call workflows.purchases.tasks.tcg_mp_selling.generate_tcg_listings
```

## Safety Notes

- Missing notes are not processed by listing, update, or radar tasks.
- Mapping creates notes by default because it is the metadata seeding step.
- Listing quantity is based on note-backed listable inventory, not every tradable
  EchoMTG copy.
- Pending orders are reserved before listing creation and update.
- Handed-off orders are accounted for before quantity is raised.
- Radar runs before updater in the scheduled chain.
- If radar fails, the updater is skipped.
- Manual radar apply only acts on rows explicitly approved in the CSV.
- Worker functions re-import dependencies inside function bodies where needed for
  multiprocessing on Windows.

## Manifesto alignment

See [`docs/MANIFESTO.md`](../../docs/MANIFESTO.md) and [`docs/thesis/MANIFESTO-REPO-UPDATES.md`](../../docs/thesis/MANIFESTO-REPO-UPDATES.md). The same metadata is persisted on each beat entry's `'manifesto'` key in `tasks_config.py`.

| Task | code_role | para_bucket | express_target | review_artifact | hfl_signal |
| --- | --- | --- | --- | --- | --- |
| `generate_tcg_mappings` | organize | area | `file:tcg_mappings` | `es_log+file` | `False` |
| `generate_tcg_listings` | express | area | `api:tcg_mp` | `es_log+file` | `False` |
| `reconcile_then_update_tcg_listings` | express | area | `api:tcg_mp` | `es_log+file` | `False` |
| `download_scryfall_bulk_data` | capture | area | `file:scryfall_bulk` | `es_log+file` | `False` |
| `generate_audit_for_tcg_orders` | distill | area | `es_log` | `es_log` | `False` |
