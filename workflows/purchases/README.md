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
| `generate_audit_for_tcg_orders` | Every 4 hours | Audit open/pending TCG orders |
| `update_tcg_listings_prices` | Daily at 2am and noon | Recalculate and update listing prices |
| `generate_tcg_mappings` | **Disabled** (commented out) | Regenerate TCG task mapping file |

## Task Files

| File | Tasks / Functions |
|------|-------------------|
| `tasks/tcg_mp_selling.py` | `download_scryfall_bulk_data`, `generate_audit_for_tcg_orders`, `update_tcg_listings_prices`, `generate_tcg_listings` (manual only) |

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
