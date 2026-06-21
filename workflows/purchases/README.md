# Purchases Workflow

## Description

- Automates the MTG card resale pipeline on The TCG Marketplace.
- Pipeline: Scryfall bulk download → card matching → listing generation → price updates → order audit.
- Uses multiprocessing (4 workers) for listing generation on Windows.

## Queue

Tasks run on the `tcg` queue.

## Scheduled Tasks

Daily pipeline, in order: **mappings → listings**; the rest hang off it.

| Task | Schedule (`tasks_config.py`) | Description |
|------|----------|-------------|
| `generate_tcg_mappings` | Daily 00:00 | Map EchoMTG cards → TCG product + Scryfall; write the per-card note |
| `generate_tcg_listings` | Daily 01:00 | Create TCG listings for mapped cards (`language` kwarg, default `EN`) |
| `radar_sold_inventory` | Monthly, 1st 03:00 | **Destructive (high-confidence tier only)** sold-inventory cleanup + full CSV review list |
| `update_tcg_listings_prices` | Weekly, Mon 04:00 | Recalculate prices; set listing quantity = EchoMTG copy count; reset vanished listings |
| `download_scryfall_bulk_data` | Monthly, 1st 22:00 | Download full Scryfall card DB (moved off 00:00 to avoid the mappings read race) |
| `generate_audit_for_tcg_orders` | Every 4 hours | Audit TCG orders across all tracked states (incl. **Cancelled / Not Received**) → ES `tcg-mp-audit-current` + `tcg-mp-status-audit` |

**How they work together / sequencing notes:**
- `mappings` (00:00) must precede `listings` (01:00) — listings consume the notes mappings writes.
- On the 1st: `radar` (03:00) cleans sold inventory **before** the weekly `update_tcg_listings_prices`
  (Mon 04:00) recomputes quantities, so quantities don't overcount sold-but-unremoved copies (#1).
- `radar` is monthly + **high-confidence-only auto-apply** (`min_confidence='high'`,
  `orphan_mode='corroborated'`): it auto-actions only the strong `listing_gone` + sold-order
  signal; medium "still listed" matches and low orphans go to the CSV (`results/`) for
  manual approve-and-apply via `/radar-sold-inventory`. Flip `dry_run=True` for report-only.
- Residual loop risk (#2): between monthly radar runs the daily `listings` can transiently
  re-list a freshly sold-but-unremoved card until the next radar/audit — run radar (or the
  approved-CSV apply) more often for tighter control.
- `download_scryfall_bulk_data` moved 00:00 → 22:00 on the 1st so it no longer writes the
  all-cards file while `mappings` reads it.

## Task Files

| File | Tasks / Functions |
|------|-------------------|
| `tasks/tcg_mp_selling.py` | `generate_tcg_mappings`, `generate_tcg_listings`, `update_tcg_listings_prices`, `download_scryfall_bulk_data`, `generate_audit_for_tcg_orders` |
| `tasks/sold_inventory_radar.py` | `radar_sold_inventory` (scan/clean) + `apply_radar_approvals` (approve-and-apply from CSV) |

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
cheap) **UNION** a fresh live poll of the order API. Sold-evidence statuses:
Completed, Picked Up, Cancelled, Not Received.

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
   approved rows only, marks sold in EchoMTG earnings + removes inventory + delists on
   TCG MP, writing an audit CSV `results/sold_inventory_radar-applied-<ts>.csv` with
   per-row `action_results`.

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

> The scheduled beat entry runs `radar_sold_inventory` in scan/report mode; applying is
> always operator-driven via the approved CSV (no unattended destructive runs).

## Known issues in `tcg_mp_selling.py` — status

Found while building the radar; walked through and resolved/triaged:

1. **Quantity overcount → unfulfillable listings** — *mitigated by data hygiene.*
   `update_tcg_listings_prices` sets a listing's `quantity` to the count of matching
   EchoMTG copies, which is **correct** *if inventory is accurate*. The bug was stale
   inventory (sold copies never removed). `radar_sold_inventory` keeps inventory clean
   (remove sold copies; the radar's own apply also reconciles listing quantity to the
   remaining copies). Run radar before/with update-prices — see the schedule. No code
   change to the quantity logic (it was right); the fix is keeping inventory true.
2. **Sold → auto-relist loop** — *mitigated by radar + sequencing.* When `edit_listing`
   returns `''` (listing gone) the worker resets `tcg_mp_listing_id = 0` and
   `generate_tcg_listings` recreates it. That's **correct** when the listing was merely
   removed and you still own the card; it's **wrong** only when the card was sold and
   not removed. The radar's `listing_gone` detection finds exactly that and removes the
   orphan, so it won't be re-listed. Residual: between monthly radar runs, a freshly
   sold-but-unremoved card can be transiently re-listed by the daily `generate_tcg_listings`
   until the next radar/audit — run radar (or approve-and-apply) more often for tighter
   control. The selling logic was intentionally left unchanged.
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
