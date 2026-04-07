# OANDA Integration (`apps/oanda`)

OANDA v20 REST API integration for forex trading — accounts, trades, orders, positions, transactions, pricing, and candlestick data.

References:
- [OANDA v20 REST API](https://developer.oanda.com/rest-live-v20/introduction/)
- [OANDA Developer Portal](https://developer.oanda.com/)

## Supported Automations

- [X] webservices
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] internet of things

---

## Setup

### 1. Get an OANDA Bearer Token

1. Log in to your OANDA account at [fxtrade.oanda.com](https://fxtrade.oanda.com)
2. Go to **My Account → Manage API Access**
3. Generate a Personal Access Token
4. Copy the token and your MT4 Account ID

### 2. Environment Variables

`.env/apps.env`:

```env
OANDA_BEARER_TOKEN=your_bearer_token
OANDA_MT4_ACCOUNT_ID=your_mt4_account_id
```

### 3. Configuration (`apps_config.yaml`)

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
    token: ${OANDA_BEARER_TOKEN}
    mt4AccountID: ${OANDA_MT4_ACCOUNT_ID}
  return_data_only: True
```

> **Practice accounts** use `https://api-fxpractice.oanda.com/v3/` instead.

---

## API Services

### `ApiServiceOandaAccount`

| Method | Description |
|--------|-------------|
| `get_account_info()` | List all accounts |
| `get_account_details(account_id)` | Full account details (balance, NAV, trade/position counts) |
| `get_account_summary(account_id)` | Lightweight account summary |
| `get_account_instrument_details(account_id, currency_name)` | Tradeable instruments |
| `get_account_changes(account_id, since_transaction_id)` | Changes since a transaction ID |
| `configure_account(account_id, alias, margin_rate)` | Update account alias/margin rate |

---

### `ApiServiceTrades`

| Method | Description |
|--------|-------------|
| `get_trades_from_account(account_id, **kwargs)` | Trade history (filters: instrument, state, count) |
| `get_open_trades_from_account(account_id)` | All currently open trades |
| `get_trade(account_id, trade_specifier)` | Single trade by ID |
| `close_trade(account_id, trade_specifier, units)` | Close a trade (fully or partially) |
| `update_trade_client_extensions(account_id, trade_specifier, body)` | Update client extensions |
| `update_trade_orders(account_id, trade_specifier, orders_body)` | Modify attached TP/SL/trailing stop |

---

### `ApiServiceOandaOrders`

| Method | Description |
|--------|-------------|
| `create_order(account_id, order_body)` | Create a new order |
| `get_orders(account_id, instrument, state, count)` | List orders with optional filters |
| `get_pending_orders(account_id)` | All pending orders |
| `get_order(account_id, order_specifier)` | Single order by ID |
| `replace_order(account_id, order_specifier, order_body)` | Replace an existing order |
| `cancel_order(account_id, order_specifier)` | Cancel a pending order |
| `update_order_client_extensions(account_id, order_specifier, body)` | Update client extensions |

---

### `ApiServiceOandaPositions`

| Method | Description |
|--------|-------------|
| `get_positions(account_id)` | All positions (open and closed) |
| `get_open_positions(account_id)` | All currently open positions |
| `get_position(account_id, instrument)` | Position for a specific instrument |
| `close_position(account_id, instrument, long_units, short_units)` | Close a position |

---

### `ApiServiceOandaTransactions`

| Method | Description |
|--------|-------------|
| `get_transactions(account_id, from_time, to_time, page_size, type)` | Paginated transaction history |
| `get_transaction(account_id, transaction_id)` | Single transaction by ID |
| `get_transactions_id_range(account_id, from_id, to_id, type)` | Transactions within an ID range |
| `get_transactions_since_id(account_id, transaction_id, type)` | Transactions since an ID |

---

### `ApiServiceOandaPricing`

| Method | Description |
|--------|-------------|
| `get_prices(account_id, instruments, since_time)` | Current bid/ask prices for one or more instruments |
| `get_candles_latest(account_id, candle_specifications, units)` | Latest candles for specifications |
| `get_instrument_candles(account_id, instrument, granularity, count, ...)` | OHLC candles (account-scoped) |

---

### `ApiServiceOandaInstruments`

Not account-scoped — uses `/v3/instruments` directly.

| Method | Description |
|--------|-------------|
| `get_candles(instrument, granularity, count, from_time, to_time, price)` | OHLC candlestick data |
| `get_order_book(instrument, time)` | Order book snapshot at price levels |
| `get_position_book(instrument, time)` | Position book snapshot at price levels |

**Granularity values:** `S5`, `S10`, `S15`, `S30`, `M1`, `M2`, `M4`, `M5`, `M10`, `M15`, `M30`, `H1`, `H2`, `H3`, `H4`, `H6`, `H8`, `H12`, `D`, `W`, `M`

**Price components:** `M` (mid), `B` (bid), `A` (ask), `BA`, `MBA`

---

## DTOs

| File | Contents |
|------|---------|
| `dto/user_account.py` | `DtoAccountProperties`, `DtoAccountDetails`, `DtoAccountInstruments` |
| `dto/orders.py` | `DtoOrder`, `DtoMarketOrder`, `DtoFixedLimitOrder`, `DtoStopOrder`, `DtoTakeProfitOrder`, etc. |
| `dto/transactions.py` | `DtoTransactions`, `DtoCreateTransaction`, `EnumTransactionType`, client extension DTOs |
| `dto/order_requests.py` | Order request bodies |
| `dto/price.py` | `DtoPrice` — bid/ask/mid price data |

---

## Tests

```sh
# Run all OANDA tests
pytest apps/oanda/tests/ -v

# Specific service
pytest apps/oanda/tests/test_pricing.py -v
pytest apps/oanda/tests/test_instruments.py -v
pytest apps/oanda/tests/test_positions.py -v
pytest apps/oanda/tests/test_orders.py -v
pytest apps/oanda/tests/test_transactions.py -v

# Smoke tests only
pytest apps/oanda/tests/ -m smoke -v
```

All tests are live integration tests against the real OANDA API. Requires valid `OANDA_BEARER_TOKEN`.

---

## MCP Tools Summary

| Tool | Description |
|------|-------------|
| `get_oanda_accounts` | List all accounts |
| `get_oanda_account_details` | Full account details |
| `get_oanda_account_summary` | Lightweight account summary |
| `get_oanda_open_trades` | Currently open trades |
| `get_oanda_trades` | Trade history with filters |
| `get_oanda_trade` | Single trade details |
| `get_oanda_prices` | Current bid/ask prices for instruments |
| `get_oanda_candles` | OHLC candles (account-scoped) |
| `get_oanda_instrument_candles` | OHLC candles (no account needed) |
| `get_oanda_order_book` | Order book snapshot |
| `get_oanda_position_book` | Position book snapshot |
| `get_oanda_orders` | Order list with filters |
| `get_oanda_pending_orders` | All pending orders |
| `get_oanda_positions` | All positions |
| `get_oanda_open_positions` | Currently open positions |
| `get_oanda_transactions` | Transaction history pages |
| `get_oanda_transaction` | Single transaction details |

## Notes

- Bearer token is set in `BaseApiServiceAppOanda.__init__()` as an `Authorization` header.
- The `mt4AccountID` is the numeric account ID shown in the OANDA web interface.
- The `hud` workflow task `show_forex_account` runs every 15 minutes on weekdays.
- `ApiServiceOandaInstruments` does **not** extend account-scoped endpoints — it calls `/v3/instruments` directly.
