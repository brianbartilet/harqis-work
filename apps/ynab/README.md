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
| `ApiServiceYNABTransactions` | `web/api/transactions.py` | `get_transactions(budget_id)`, `get_transactions_per_account(budget_id, account_id)`, `create_new_transaction(budget_id, tx)`, `update_transaction(budget_id, tx)` |

## DTOs

| Class | File | Description |
|-------|------|-------------|
| `DtoSaveTransaction` | `dto/transaction.py` | Payload for creating a new transaction |
| `DtoUpdateTransaction` | `dto/transaction.py` | Payload for updating an existing transaction |
| `DtoAccount` | `dto/account.py` | YNAB account record |

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
from apps.ynab.references.web.api.transactions import ApiServiceYNABTransactions
from apps.ynab.references.dto.transaction import DtoSaveTransaction
from apps.ynab.config import CONFIG

tx_svc = ApiServiceYNABTransactions(CONFIG)

# Create a transaction
new_tx = DtoSaveTransaction(
    account_id='<account-uuid>',
    date='2026-03-25',
    amount=-50000,      # milliunits: -50.00 PHP
    payee_name='TCG Marketplace',
    memo='Card sale proceeds'
)
tx_svc.create_new_transaction(CONFIG.app_data['budget_php'], new_tx)
```

## Notes

- Authentication uses a Personal Access Token (Bearer) — generate at `app.ynab.com/settings/developer`.
- YNAB amounts are in **milliunits** (1 currency unit = 1000 milliunits). A $50 expense is `-50000`.
- The `hud` workflow task `show_ynab_budgets_info` runs every 4 hours.
- Multiple budget IDs (PHP, SGD) are configured to support multi-currency tracking.
