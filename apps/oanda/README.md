# Oanda

## Description

- [Oanda](https://www.oanda.com/) is a forex trading platform supporting currency pairs, indices, and commodities.
- Uses the [OANDA REST API v20](https://developer.oanda.com/rest-live-v20/introduction/) with Bearer token authentication.
- Used in the `hud` workflow to display live forex account balance and open trades on the desktop HUD.

## Supported Automations

- [X] webservices
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] internet of things

## API Services

| Class | File | Methods |
|-------|------|---------|
| `ApiServiceOandaAccount` | `web/api/account.py` | `get_account_info()`, `get_account_details(account_id)`, `get_account_instrument_details(account_id, currency_name)` |
| `ApiServiceTrades` | `web/api/open_trades.py` | `get_trades_from_account(account_id, **kwargs)`, `get_open_trades_from_account(account_id)` |

## DTOs

| Class | File | Description |
|-------|------|-------------|
| `DtoAccountProperties` | `dto/user_account.py` | Summary of an account (id, alias, currency, etc.) |
| `DtoAccountDetails` | `dto/user_account.py` | Full account details including NAV, balance, P&L |
| `DtoAccountInstruments` | `dto/user_account.py` | Tradable instrument details |
| `DtoPrice` | `dto/price.py` | Bid/ask price data |
| `DtoOrderRequests` | `dto/order_requests.py` | Order placement payload |
| `DtoOrders` | `dto/orders.py` | Order record |
| `DtoTransactions` | `dto/transactions.py` | Transaction history record |

## Configuration (`apps_config.yaml`)

```yaml
OANDA:
  app_id: 'oanda'
  client: 'rest'
  parameters:
    base_url: 'https://api-fxtrade.oanda.com/v3/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 60
    stream: True
  app_data:
    bearer_token: ${OANDA_BEARER_TOKEN}
    mt4_account_id: ${OANDA_MT4_ACCOUNT_ID}
  return_data_only: True
```

`.env/apps.env`:

```env
OANDA_BEARER_TOKEN=
OANDA_MT4_ACCOUNT_ID=
```

## How to Use

```python
from apps.oanda.references.web.api.account import ApiServiceOandaAccount
from apps.oanda.config import CONFIG

svc = ApiServiceOandaAccount(CONFIG)

# List all accounts
accounts = svc.get_account_info()

# Get full account details
details = svc.get_account_details(CONFIG.app_data['mt4_account_id'])
print(details.balance, details.unrealizedPL)
```

```python
from apps.oanda.references.web.api.open_trades import ApiServiceTrades
from apps.oanda.config import CONFIG

trades = ApiServiceTrades(CONFIG)
open_positions = trades.get_open_trades_from_account(CONFIG.app_data['mt4_account_id'])
```

## Notes

- Bearer token is set in `BaseApiServiceAppOanda.__init__()` as an `Authorization` header.
- The `mt4_account_id` is the numeric account ID shown in the OANDA web interface.
- `get_account_instrument_details` accepts an optional `currency_name` filter (e.g. `EUR_USD`).
- The `hud` workflow task `show_forex_account` runs every 15 minutes on weekdays.
