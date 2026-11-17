# Finance Workflow

## Description

Financial data aggregation, transaction import, and reporting workflow.

Uses the Anthropic Claude API to parse bank statement PDFs and import transactions into YNAB with automatic category matching.

Also captures new Interactive Brokers stock trades to a local ledger and syncs them to a Google Sheet trade log (`capture_ibkr_trades`, `sync_trade_log_sheet`).

---

## Tasks

### `add_ynab_transactions_from_pdf` (`tasks/parse_transaction.py`)

Parses a bank statement PDF using Claude and imports the extracted transactions into YNAB.

**Signature:**
```python
def add_ynab_transactions_from_pdf(input_pdf, ynab_budget_name, ynab_account_name, **kwargs)
```

**Arguments:**

| Arg | Type | Description |
|-----|------|-------------|
| `input_pdf` | `str` | PDF filename inside `workflows/finance/transactions/` |
| `ynab_budget_name` | `str` | YNAB budget name as shown in the app (e.g. `'SGD Budget'`) |
| `ynab_account_name` | `str` | Account name within that budget (e.g. `'DBS Checking'`) |
| `cfg_id__ynab` | `str` (kwarg) | Config key for YNAB, default `'YNAB'` |

**What it does:**

1. Reads the PDF from `workflows/finance/transactions/<input_pdf>`
2. Encodes it as base64 and sends it to Claude with a structured parsing prompt
3. Claude extracts each transaction: date, memo, amount, debit/credit, payee, category hint
4. Resolves the YNAB budget ID and account ID by name
5. Fuzzy-matches Claude's `category_hint` against real YNAB category names
6. Converts amounts to YNAB milliunits (negative = outflow, positive = inflow)
7. POSTs all transactions to YNAB in a single batch call

**YNAB field mapping:**

| Claude output | YNAB field |
|--------------|-----------|
| `memo` | `memo` (truncated to 200 chars) |
| `payee_name` | `payee_name` |
| `date` | `date` (ISO `YYYY-MM-DD`) |
| `amount` × `type` | `amount` in milliunits (negative = debit) |
| `category_hint` | `category_id` (fuzzy matched) |

**Decorators:** `@SPROUT.task(queue='default')`, `@log_result()`, `@feed()`

---

### IBKR trade log — two independent tasks

**Goal:** Record every new Interactive Brokers stock trade in a Google Sheet within ~35 minutes of the fill, and keep deposits and dividends tabs up to date.

The process is split into two operations that never call each other's service, joined by a local ledger:

```
capture_ibkr_trades  (IBKR only)   IBKR Flex TradeConfirm XML → stocks, date ≥ IBKR_CAPTURE_START_DATE, new execID
                                    → append to ${HARQIS_DATA_ROOT}/finance/ibkr_trades.jsonl  (default .harqis-data/, gitignored)

sync_trade_log_sheet (Google only)  ledger entries whose trade ID is not in the sheet → append rows to the trade log sheet
```

Capture reads both IBKR queries when configured: Trade Confirmation (only *Today* is offered, near real time) and Activity (rolling week, after IBKR's end-of-day processing). Executions are de-duplicated by `tradeID` and by symbol + time + quantity + price, so the overlap is harmless.

**Deposits / withdrawals:** the Activity query's **Cash Transactions → Deposits & Withdrawals** section is captured in the same download into `ibkr_cash.jsonl` (by transaction ID), and the sync writes them to the template's optional `deposits` tab: withdrawals as negative amounts, Notes `IBKR deposit (auto)` / `IBKR withdrawal (auto)`, filtered by `match` (e.g. SGD only; others are reported). With `insert_above_blank_row: true`, new rows are inserted above the first blank row under the data, so a total row below (e.g. `=SUM(B2:B26)` spanning the spacer) is pushed down and its range grows. Rows entered by hand are recognised by date + amount.

**Dividends:** cash transactions of type Dividends, Payment In Lieu Of Dividends and Withholding Tax are captured into the same cash ledger. The sync groups them per IBKR action ID and payment date into one row (gross, withholding tax, net, FX to base, net in base currency) on the template's optional `dividends` tab, which is created on first sync (`create_if_missing`). Later corrections, e.g. a withholding refund, land as their own *Tax adjustment* row, so written rows never change. Backfill past dividends once with `capture-history --from YYYY-MM-DD`: it requests the Activity query with explicit `fd`/`td` date ranges in chunks of ≤ 365 days, up to yesterday (IBKR only serves processed days), and only for dividend types, so trades and deposits keep their own start date.

If Google access lapses, captures continue and the sheet catches up on the next sync; if IBKR is down, the sheet is untouched.

| | `capture_ibkr_trades` (`tasks/ibkr_trades.py`) | `sync_trade_log_sheet` (`tasks/trade_log_sheet.py`) |
|---|---|---|
| **Logic** | `workflows/finance/ibkr_ledger.py` | `workflows/finance/sheets_sync.py` |
| **Apps** | `apps/ibkr` (read-only Flex token) | `apps/google_apps` (`ApiServiceGoogleSheets.append_values`) |
| **Config key** | `IBKR` | `GOOGLE_SHEETS_TRADE_LOG` |
| **Env vars** | `IBKR_FLEX_TOKEN`, `IBKR_FLEX_QUERY_ID_TRADES` (Trade Confirmation, Today) and/or `IBKR_FLEX_QUERY_ID_ACTIVITY` (Activity → Trades, last 7 days; backfill + missed runs), `IBKR_CAPTURE_START_DATE` | `TRADE_LOG_SHEET_ID` (Sheets API enabled on the OAuth client; token in `.env/storage_sheets.json`) |
| **Parked schedule** | `crontab(minute='*/30')` | `crontab(minute='5,35')` |
| **Output** | Appends to the trade and cash ledgers | Appends trade rows; inserts deposit rows |

**Runtime:** `celery` — deterministic, no LLM. Both logic modules are free of Celery imports so they also run from `scripts/ibkr_trade_log.py`.

**Schedule owner:** `manual` / Windows Task Scheduler (`scripts/ibkr_trade_log.py run`) until the finance workflow is activated in Beat — see the parked entries in `tasks_config.py` (`WorkflowQueue.DEFAULT`). Use only one schedule owner.

**OS:** cross-platform

**Sheet template:** `templates/trade_log_sheet.yaml` is the generic default (one `Trades` tab, one row per execution); `create-sheet` builds a new sheet from it. To use an **existing** sheet, put a personal template at `${HARQIS_DATA_ROOT}/finance/trade_log_sheet.yaml` (default `.harqis-data/finance/`, gitignored) or point `TRADE_LOG_TEMPLATE` at one. A template can:

- **route** records to different tabs by `match` (e.g. `currency: USD` → a USD tab, `currency: SGD` → an SGX tab with `symbol_prefix: "SGX: "`); unmatched records are reported, not written;
- **group by order** (`group_by: order`) so partial fills become one row with a volume-weighted price and summed fees;
- map headers to fields (`signed_quantity` writes sells as negative numbers) or to constants (`{header: Platform, value: IBKR}`).

Columns are matched **by header text in row 1**, in the sheet's own order; only columns up to the last mapped header are written, and new rows fill the empty rows under the table (no row insertion), so summary blocks beside or on other tabs are untouched. `prepare-sheet` adds missing template headers (e.g. the ID column) into the first empty row-1 cells. Rows entered by hand (blank ID) are recognised by symbol + date + quantity and not duplicated. Symbols new to a tab are reported so formula-based summaries can be extended; with a route `summary: {tab, symbol_column}` the sync adds the row itself — symbol plus formulas generated from the block's first data row (row-local references move, ranges into the data stay, so each row covers the whole table), placed under the last listed symbol and never over existing cells.

**Failure behavior:** each operation raises on missing config or API errors and writes nothing on failure (IBKR `GetStatement` is retried while the report is still generating, code 1019). Both are idempotent — selection is by execution ID, not by time window — so a missed run is caught up by the next one.

**Setup:**
```sh
python scripts/ibkr_trade_log.py create-sheet     # new sheet from the template; set TRADE_LOG_SHEET_ID
python scripts/ibkr_trade_log.py prepare-sheet --dry-run   # or: add missing headers to an existing sheet
python scripts/ibkr_trade_log.py run --dry-run    # preview capture + sync
python scripts/ibkr_trade_log.py run              # capture, then sync (sync still runs if capture fails)
python scripts/ibkr_trade_log.py capture | sync   # either operation on its own
python scripts/ibkr_trade_log.py capture-history --from 2025-01-01   # one-off dividend backfill
```

---

### Running unattended (cloud runner or another host)

The trade log only needs a small part of the stack:

```sh
pip install -r workflows/finance/requirements-trade-log.txt
pip install --no-deps "<the harqis-core line from requirements.txt>"
python scripts/ibkr_trade_log.py run
```

Configuration comes from environment variables instead of local files (nothing personal is committed):

| Variable | Value |
|---|---|
| `APP_CONFIG_FILE` | `apps_config.yaml` |
| `IBKR_FLEX_TOKEN`, `IBKR_FLEX_QUERY_ID_TRADES`, `IBKR_FLEX_QUERY_ID_ACTIVITY`, `IBKR_CAPTURE_START_DATE` | as in `.env/apps.env` |
| `TRADE_LOG_SHEET_ID` | the spreadsheet ID |
| `GOOGLE_SERVICE_ACCOUNT` | the service-account key **JSON content** (locally: a key file name in `.env/`) |
| `TRADE_LOG_TEMPLATE_YAML` | optional: the personal template's YAML content |

**Google service account** (recommended for unattended runs): browser sign-ins in an OAuth app's *Testing* mode expire every 7 days, a service account does not. Create one in the same Cloud project (IAM & Admin → Service Accounts, no roles), add a JSON key, and **share the spreadsheet with the account's email as Editor**; it can reach nothing else. Any Google config with `service_account: ${GOOGLE_SERVICE_ACCOUNT}` then uses it instead of the browser token.

The ledgers are only a hand-off between capture and sync, so a runner without persistent storage still works: de-duplication is against the IDs already in the sheet, and the Activity query's rolling week covers runs that were missed.

---

## Running Manually (pytest / ad-hoc)

```python
# From a pytest test or Python shell:
from workflows.finance.tasks.parse_transaction import add_ynab_transactions_from_pdf

result = add_ynab_transactions_from_pdf(
    input_pdf="transaction_history_07042026.pdf",
    ynab_budget_name="SGD Budget",
    ynab_account_name="DBS Checking",
)
print(result)
```

Or via Celery `.apply()` for local synchronous execution:

```python
result = add_ynab_transactions_from_pdf.apply(
    kwargs={
        "input_pdf": "transaction_history_07042026.pdf",
        "ynab_budget_name": "SGD Budget",
        "ynab_account_name": "DBS Checking",
    }
).get()
```

---

## Prompt

The parsing prompt is at `workflows/finance/prompts/parse_transaction.md`.

It instructs Claude to:
- Extract date, memo, amount, debit/credit type, payee name, and category hint
- Return pure JSON (no markdown fences)
- Skip headers, subtotals, and balance lines
- Never invent data — use `null` for unknown fields

---

## Transactions Folder

PDFs go in `workflows/finance/transactions/`. This folder is tracked in git (via `.gitkeep`) but its contents are ignored (via `.gitignore`).

---

## Tests

```sh
# Unit tests only (no API calls)
pytest workflows/finance/tests/test_parse_transaction.py -v -k "not smoke"

# All tests including live API calls
pytest workflows/finance/tests/test_parse_transaction.py -v

# Set PDF/budget/account via env vars
TEST_PDF_FILENAME=my_statement.pdf \
TEST_YNAB_BUDGET="SGD Budget" \
TEST_YNAB_ACCOUNT="DBS Checking" \
pytest workflows/finance/tests/test_parse_transaction.py -v
```

IBKR trade log: `pytest -o addopts="" workflows/finance/tests/test_ibkr_ledger.py workflows/finance/tests/test_sheets_sync.py -v` (unit tests are offline; live dry runs need IBKR / Sheets config; writing tests are skipped).

The full import test (`test_full_workflow_task`) is **skipped by default** — it posts real data to YNAB. Remove the `@pytest.mark.skip` decorator when ready to run.

---

## App Dependencies

| App | Use |
|-----|-----|
| `antropic` | Parse PDF via Claude (document vision + JSON extraction) |
| `ynab` | Resolve budget/account IDs, fetch categories, post transactions |
| `ibkr` | Trade Confirmation Flex Query (read-only) for `capture_ibkr_trades` |
| `google_apps` | Sheets read/append for `sync_trade_log_sheet` |

---

## Activating in `workflows/config.py`

This workflow is not yet in the Celery Beat schedule. To add it:

```python
from workflows.finance.tasks_config import WORKFLOW_FINANCE

CONFIG_DICTIONARY = ... | WORKFLOW_FINANCE
```

Task registration: `workflows/finance/__init__.py` imports the IBKR trade-log task modules
only when Celery is already loaded (worker, Beat, or a process that imported the SPROUT app),
so `scripts/ibkr_trade_log.py` can import the Celery-free logic modules without the worker stack.

---

## Planned Scope

| Task | Status |
|------|--------|
| PDF → YNAB transaction import | ✅ Implemented |
| OANDA + TCG P&L aggregation | Planned |
| IBKR trades → ledger → Google Sheets trade log | ✅ Implemented |
| Google Sheets reporting | Planned |
| HUD finance summary | Planned |
