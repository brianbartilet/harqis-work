# Finance Workflow

## Description

- Planned workflow for financial data aggregation and reporting.
- Currently a **stub** — no tasks are defined.

## Status

This workflow is empty. Only `__init__.py` exists with no task implementations or schedule configuration.

## Planned Scope

When implemented, this workflow is intended to:
- Aggregate transactions from YNAB, OANDA, and TCG Marketplace into a unified financial report.
- Generate periodic P&L summaries across currencies (PHP, SGD).
- Push financial snapshots to the desktop HUD or Google Sheets.

## App Dependencies (planned)

| App | Planned Use |
|-----|-------------|
| `ynab` | Budget and transaction data |
| `oanda` | Forex account balance and trade history |
| `tcg_mp` | Card sale revenue |
| `google_apps` | Write reports to Google Sheets |

## Activating in `workflows/config.py`

Once tasks are defined, register in `workflows/config.py`:

```python
from workflows.finance.tasks_config import WORKFLOW_FINANCE

CONFIG_DICTIONARY = ... | WORKFLOW_FINANCE
```

## Notes

- No Celery Beat schedule is defined.
- Not merged into `workflows/config.py`.
