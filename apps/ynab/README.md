# You Need A Budget (YNAB)

## Description

- [YNAB](https://www.ynab.com) is a zero-based budgeting application.
- Provides a [REST API](https://api.ynab.com/) for automating budget queries and transaction management.
- Primary use case: consolidate financial transactions from multiple sources (OANDA, TCG sales, etc.) and categorize them in YNAB.
- Used in the `hud` workflow to display budget balances for PHP and SGD budgets on the desktop HUD.

## Supported Automations

- [X] webservices
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] internet of things

## API Services

| Class | File | Methods |
|-------|------|---------|
| `ApiServiceYNABUser` | `web/api/user.py` | `get_user_info()` |
| `ApiServiceYNABBudgets` | `web/api/budgets.py` | `get_budgets()`, `get_budget_info(budget_id)`, `get_accounts(budget_id)`, `get_categories(budget_id)` |
| `ApiServiceYNABTransactions` | `web/api/transactions.py` | `get_transactions(budget_id)`, `get_transactions_per_account(budget_id, account_id)`, `get_transaction(budget_id, tx_id)`, `create_new_transaction(budget_id, body)`, `update_transaction(budget_id, tx_id, body)`, `delete_transaction(budget_id, tx_id)` |
| `ApiServiceYNABCategories` | `web/api/categories.py` | `get_categories(budget_id)`, `get_category(budget_id, category_id)`, `get_month_category(budget_id, month, category_id)`, `update_month_category(budget_id, month, category_id, budgeted)` |
| `ApiServiceYNABPayees` | `web/api/payees.py` | `get_payees(budget_id)`, `get_payee(budget_id, payee_id)` |
| `ApiServiceYNABMonths` | `web/api/months.py` | `get_months(budget_id)`, `get_month(budget_id, month)` |
| `ApiServiceYNABScheduledTransactions` | `web/api/scheduled_transactions.py` | `get_scheduled_transactions(budget_id)`, `get_scheduled_transaction(budget_id, id)`, `create_scheduled_transaction(budget_id, body)`, `update_scheduled_transaction(budget_id, id, body)`, `delete_scheduled_transaction(budget_id, id)` |

> Write methods (`create_*`, `update_*`) take the **full request body** wrapped under the YNAB key (`transaction`, `scheduled_transaction`, `category`), e.g. `{"transaction": {...}}`. The MCP layer builds these wrappers for you.

## DTOs

| Class | File | Description |
|-------|------|-------------|
| `DtoSaveTransaction` | `dto/transaction.py` | Payload for creating a new transaction |
| `DtoUpdateTransaction` | `dto/transaction.py` | Payload for updating an existing transaction |
| `DtoSaveScheduledTransaction` | `dto/transaction.py` | Payload for a scheduled transaction (incl. `frequency`) |
| `DtoUpdateScheduledTransaction` | `dto/transaction.py` | Payload for updating a scheduled transaction |
| `DtoAccount` | `dto/account.py` | YNAB account record |

## MCP Tools

Registered by `register_ynab_tools` in `apps/ynab/mcp.py`:

| Tool | Description |
|------|-------------|
| `get_ynab_budgets` / `get_ynab_budget_summary` / `get_ynab_accounts` | Budgets and accounts |
| `get_ynab_categories` | All category groups/categories |
| `get_ynab_transactions` / `get_ynab_account_transactions` / `get_ynab_transaction` | View transactions |
| `create_ynab_transaction` / `update_ynab_transaction` / `delete_ynab_transaction` | Transaction write ops (delete is destructive) |
| `analyze_ynab_uncategorized` | List uncategorized transactions + available categories |
| `categorize_ynab_transaction` | Assign a category to a transaction |
| `get_ynab_month_category` / `update_ynab_month_category` | Read/assign a category's budgeted amount for a month |
| `get_ynab_payees` | All payees |
| `get_ynab_month` / `get_ynab_months` | Monthly budget plan (single month or all) |
| `get_ynab_scheduled_transactions` / `get_ynab_scheduled_transaction` | View scheduled transactions |
| `create_ynab_scheduled_transaction` / `update_ynab_scheduled_transaction` / `delete_ynab_scheduled_transaction` | Scheduled transaction write ops (delete is destructive) |

> Amounts are in **milliunits** (1 unit = 1000). Months are ISO dates (`'2026-06-01'`) or `'current'`.

## Configuration (`apps_config.yaml`)

```yaml
YNAB:
  app_id: 'ynab'
  client: 'rest'
  parameters:
    base_url: 'https://api.ynab.com/v1/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 60
    stream: True
  app_data:
    access_token: ${YNAB_ACCESS_TOKEN}
    budget_php: ${YNAB_BUDGET_PHP}
    budget_sgd: ${YNAB_BUDGET_SGD}
  return_data_only: True
```

`.env/apps.env`:

```env
YNAB_ACCESS_TOKEN=
YNAB_BUDGET_PHP=    # Budget ID for PHP budget (UUID from YNAB)
YNAB_BUDGET_SGD=    # Budget ID for SGD budget (UUID from YNAB)
```

> Budget IDs can be found in the YNAB web app URL: `app.ynab.com/budgets/<budget-id>/...`

## How to Use

```python
from apps.ynab.references.web.api.budgets import ApiServiceYNABBudgets
from apps.ynab.config import CONFIG

svc = ApiServiceYNABBudgets(CONFIG)

# List all budgets
budgets = svc.get_budgets()

# Get accounts in the PHP budget
accounts = svc.get_accounts(CONFIG.app_data['budget_php'])
```

```python
from dataclasses import asdict
from apps.ynab.references.web.api.transactions import ApiServiceYNABTransactions
from apps.ynab.references.dto.transaction import DtoSaveTransaction
from apps.ynab.config import CONFIG

tx_svc = ApiServiceYNABTransactions(CONFIG)

# Create a transaction — the method takes the full request body wrapped under "transaction"
new_tx = DtoSaveTransaction(
    account_id='<account-uuid>',
    date='2026-03-25',
    amount=-50000,      # milliunits: -50.00 PHP
    payee_name='TCG Marketplace',
    memo='Card sale proceeds'
)
created = tx_svc.create_new_transaction(CONFIG.app_data['budget_php'], {"transaction": asdict(new_tx)})

# Update / delete by transaction id
tx_id = created['transaction']['id']
tx_svc.update_transaction(CONFIG.app_data['budget_php'], tx_id, {"transaction": {"memo": "reconciled"}})
tx_svc.delete_transaction(CONFIG.app_data['budget_php'], tx_id)
```

## Future Migration — Official Python SDK

This integration is a hand-rolled REST client built on `BaseFixtureServiceRest`. YNAB now
publishes an [official Python client](https://api.ynab.com/#client-python)
(`pip install ynab`, source: [ynab-sdk-python](https://github.com/ynab/ynab-sdk-python)).

A future refactor should migrate the `web/api/*` services to wrap the official SDK:

- Replace the manual request-building in each `ApiServiceYNAB*` with the SDK's typed
  API classes (`TransactionsApi`, `CategoriesApi`, `PayeesApi`, `MonthsApi`,
  `ScheduledTransactionsApi`, `BudgetsApi`).
- Keep the current public method signatures so `apps/ynab/mcp.py` and the
  `workflows/finance` + `workflows/hud` callers stay unchanged.
- Drop the bespoke milliunit/DTO handling in favour of the SDK's generated models.

Until then, the endpoints, paths, and request-body wrappers here mirror the
[YNAB API v1 spec](https://api.ynab.com/v1) directly.

## Notes

- Authentication uses a Personal Access Token (Bearer) — generate at `app.ynab.com/settings/developer`.
  Set `YNAB_ACCESS_TOKEN` in `.env/apps.env`; if unset, requests return `401 unauthorized`.
- YNAB amounts are in **milliunits** (1 currency unit = 1000 milliunits). A $50 expense is `-50000`.
- Budget months are ISO dates (`'2026-06-01'`) or the literal `'current'`.
- The `hud` workflow task `show_ynab_budgets_info` runs every 4 hours.
- Multiple budget IDs (PHP, SGD) are configured to support multi-currency tracking.
