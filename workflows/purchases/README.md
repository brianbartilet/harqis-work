# Purchases Workflow

## Description

- Automates the MTG card resale pipeline on The TCG Marketplace.
- Pipeline: Scryfall bulk download → card matching → listing generation → price updates → order audit.
- Uses multiprocessing (4 workers) for listing generation on Windows.

## Queue

Tasks run on the `tcg` queue.

## Scheduled Tasks

| Task | Schedule | Description |
|------|----------|-------------|
| `download_scryfall_bulk_data` | 1st of month at 2am | Download full Scryfall card database |
| `generate_audit_for_tcg_orders` | Every 4 hours | Audit TCG orders across all tracked states (incl. **Cancelled / Not Received**) → ES `tcg-mp-audit-current` + `tcg-mp-status-audit` |
| `update_tcg_listings_prices` | Daily at 2am and noon | Recalculate and update listing prices |
| `generate_tcg_mappings` | **Disabled** (commented out) | Regenerate TCG task mapping file |
| `radar_sold_inventory` | **Disabled** (commented out — monthly) | Flag/clean EchoMTG items already sold on TCG MP but still listed |

## Task Files

| File | Tasks / Functions |
|------|-------------------|
| `tasks/tcg_mp_selling.py` | `download_scryfall_bulk_data`, `generate_audit_for_tcg_orders`, `update_tcg_listings_prices`, `generate_tcg_listings` (manual only) |
| `tasks/sold_inventory_radar.py` | `radar_sold_inventory` — sold-but-still-listed detector + cleanup |

## Sold-inventory radar (`radar_sold_inventory`)

**Goal:** surface (and optionally clean up) EchoMTG inventory items that are
already **sold** on TCG MP yet are still in the inventory **and** still actively
listed — the exact state that lets a buyer order a card you can't ship. Replaces
the manual monthly "review all completed/cancelled orders → remove cards in
EchoMTG by hand" process.

**How it matches** — the per-item EchoMTG note (written by `generate_tcg_mappings`)
is the join key:

```
sold TCG order line items ──┐
  (product_id / listing_id) ├─►  note.tcg_mp_listing_id  (exact listing → HIGH confidence)
                            └─►  note.tcg_mp_card_id + foil (product → MEDIUM confidence)
                                   AND the item is still in the active TCG listings
```

**Order source (hybrid):** the ES audit index `tcg-mp-audit-current` (historical,
cheap) **UNION** a fresh live poll of the order API. Sold-evidence statuses:
Completed, Picked Up, Cancelled, Not Received.

**Apps chained:** `apps/tcg_mp` (orders, listings, delist), `apps/echo_mtg`
(inventory, notes, earnings mark-sold).

**Output (always, even when applying):**
- a **CSV** review list under `results/sold_inventory_radar-<ts>.csv` — one row per
  card with both sides: EchoMTG (emid, inventory_id, set, condition, acquired
  price/date, note join keys) **and** TCG MP (live listing id/price/quantity + the
  sold order(s) with status/qty/price), plus an **`assessment`** column that
  explains in plain English why the card was flagged (confidence, which listing/
  product was sold, in which orders, and the recommended action). `results/` is
  tracked in git but its contents are gitignored.
- one ES doc per candidate in `tcg-mp-sold-radar` (same columns as the CSV)
- a HUD feed summary line (`@feed`)

**Default behaviour is destructive** (`dry_run=False`): each qualifying candidate
is marked sold in EchoMTG earnings, removed from inventory, and delisted on TCG MP —
then included in the review list so you can physically verify after the fact. Pass
`dry_run=True` for a preview-only run, `apply_actions=(...)` to limit which actions
run, or `min_confidence='high'` to act only on exact-listing matches.

```python
from workflows.purchases.tasks.sold_inventory_radar import radar_sold_inventory
radar_sold_inventory(dry_run=True, limit=25)            # preview only
radar_sold_inventory(min_confidence='high')            # act on exact-listing matches only
```

## Known issues in `tcg_mp_selling.py` (radar rationale + bug report)

Found while building the radar. The radar + the audit change address the first
three; the rest are flagged for a future fix (the selling logic was left untouched).

1. **Quantity overcount → unfulfillable listings.** `update_tcg_listings_prices`
   sets a listing's `quantity` to the count of matching foil/non-foil EchoMTG rows.
   A sold-but-un-removed copy inflates that count, so the listing offers more than
   you hold. (Primary driver of the problem the radar detects.)
2. **Sold → auto-relist loop.** When `edit_listing` returns `''` (listing gone,
   e.g. sold/removed) the worker resets `note.tcg_mp_listing_id = 0`; the next
   `generate_tcg_listings` then re-creates the listing — re-listing a card you may
   no longer hold (the scenario documented in the worker's own comment block).
3. **Audit didn't track Cancelled/Not Received** — now fixed: `generate_audit_for_tcg_orders`
   polls those two states too (date-bounded), so the radar's ES feed is complete.
4. **Misleading note-exists log + fragile shape.** `generate_tcg_mappings` logs
   "Note already exists" in the *not-found* branch and assumes two different shapes
   of `notes_fetch['note']` (string `'not found'` vs `{'note': ...}`).
5. **`guid` may be `None` written into the note** when image-GUID extraction fails
   for every TCG search result — produces a note with `scryfall_guid=None`.
6. **Deprecated `logger.warn()`** in `_worker_update_tcg_listings_prices` — use `.warning()`.
7. **`needs_lowest_seller` is never honoured.** `_update_pricing_calc` flags it for
   down/flat price changes, but the worker never fetches the lowest seller price —
   it just applies `base_price * conversion_multiplier`. Incomplete feature.
8. **`force_generate` disables listings without re-enabling.** `generate_tcg_mappings`
   calls `set_listing_status(0)`; the re-enable is commented out, so a standalone
   run leaves listings off until `update_tcg_listings_prices` re-enables them.

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

## Pipeline Steps

### 1. Download Scryfall Data (monthly)
```python
# Triggered automatically on 1st of each month at 2am
download_scryfall_bulk_data()
# Downloads to SCRY_DOWNLOADS_PATH (env var)
```

### 2. Generate Listings (manual trigger)
```python
# Must be triggered manually via n8n or Celery CLI
generate_tcg_listings()
# Uses 4 worker processes (multiprocessing)
# Matches owned Echo MTG inventory against Scryfall data
# Creates new listings on TCG Marketplace
```

### 3. Update Prices (daily)
```python
# Runs at 2am and noon daily
update_tcg_listings_prices()
# Recalculates pricing using _update_pricing_calc()
# Uses worker pool for parallel price edits
```

### 4. Audit Orders (every 4 hours)
```python
generate_audit_for_tcg_orders()
# Fetches open orders and generates an audit report
```

## Running

```sh
# Start a worker for the tcg queue
celery -A workflows.config worker --loglevel=info -Q tcg

# Manually trigger listing generation
celery -A workflows.config call workflows.purchases.tasks.tcg_mp_selling.generate_tcg_listings
```

## Notes

- `generate_tcg_listings` is **not in the beat schedule** — it must be triggered manually or via n8n because it is a long-running task.
- `generate_tcg_mappings` is commented out in `tasks_config.py` — regenerate the mapping file manually when task names change.
- Worker functions re-import all dependencies inside the function body — required for `multiprocessing` on Windows (no `fork`).
- `logger.warn()` (deprecated) is used in `tcg_mp_selling.py` and should be updated to `logger.warning()`.
- The `_retry_edit_listing` function handles transient API failures with retry logic.

## Manifesto alignment

See [`docs/MANIFESTO.md`](../../docs/MANIFESTO.md) and [`docs/thesis/MANIFESTO-REPO-UPDATES.md`](../../docs/thesis/MANIFESTO-REPO-UPDATES.md). The same metadata is persisted on each beat entry's `'manifesto'` key in `tasks_config.py`.

| Task | code_role | para_bucket | express_target | review_artifact | hfl_signal |
| --- | --- | --- | --- | --- | --- |
| `generate_tcg_mappings` | organize | area | `file:tcg_mappings` | `es_log+file` | `False` |
| `generate_tcg_listings` | express | area | `api:tcg_mp` | `es_log+file` | `False` |
| `update_tcg_listings_prices` | express | area | `api:tcg_mp` | `es_log` | `False` |
| `download_scryfall_bulk_data` | capture | area | `file:scryfall_bulk` | `es_log+file` | `False` |
| `generate_audit_for_tcg_orders` | distill | area | `es_log` | `es_log` | `False` |
