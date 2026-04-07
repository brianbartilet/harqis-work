# Finance Workflow

## Description

Financial data aggregation, transaction import, and reporting workflow.

Uses the Anthropic Claude API to parse bank statement PDFs and import transactions into YNAB with automatic category matching.

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

The full import test (`test_full_workflow_task`) is **skipped by default** — it posts real data to YNAB. Remove the `@pytest.mark.skip` decorator when ready to run.

---

## App Dependencies

| App | Use |
|-----|-----|
| `antropic` | Parse PDF via Claude (document vision + JSON extraction) |
| `ynab` | Resolve budget/account IDs, fetch categories, post transactions |

---

## Activating in `workflows/config.py`

This workflow is not yet in the Celery Beat schedule. To add it:

```python
from workflows.finance.tasks_config import WORKFLOW_FINANCE

CONFIG_DICTIONARY = ... | WORKFLOW_FINANCE
```

---

## Planned Scope

| Task | Status |
|------|--------|
| PDF → YNAB transaction import | ✅ Implemented |
| OANDA + TCG P&L aggregation | Planned |
| Google Sheets reporting | Planned |
| HUD finance summary | Planned |
