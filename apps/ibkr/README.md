# Interactive Brokers (`apps/ibkr`)

## Description

- Read-only access to Interactive Brokers through the **Flex Web Service**: generates a saved
  Flex Query (Trade Confirmation or Activity) and parses the XML report into trades.
- No trading permission, no running TWS / IB Gateway, no daily re-login.
- API docs: [Flex Web Service](https://www.interactivebrokers.com/campus/ibkr-api-page/flex-web-service/)
- Auth: Flex Web Service token sent as the `t` query parameter on every call, plus a Flex Query ID.

## Supported Automations

- [x] webservices — REST API calls
- [ ] browser — Selenium page automation
- [ ] desktop — Local Windows automation
- [ ] mobile — Android/iOS automation
- [ ] internet of things — MQTT / hardware integration

## Directory Structure

```
apps/ibkr/
├── config.py                       # Loads the IBKR section from apps_config.yaml
├── mcp.py                          # register_ibkr_tools (get_ibkr_trades, get_ibkr_cash_transactions)
├── references/
│   ├── dto/
│   │   └── trade.py                # DtoIbkrTrade, DtoIbkrCashTransaction
│   └── web/
│       ├── base_api_service.py     # BaseApiServiceIbkr — User-Agent + per-call token
│       └── api/
│           └── flex.py             # ApiServiceIbkrFlex + XML parsing helpers
└── tests/
    ├── test_flex.py                # live smoke tests (need a Flex token)
    └── test_flex_parsing.py        # offline parser / retry tests
```

## Configuration

`apps_config.yaml`:

```yaml
IBKR:
  app_id: 'ibkr'
  client: 'rest'
  parameters:
    base_url: 'https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 60
    stream: False
  app_data:
    flex_token: ${IBKR_FLEX_TOKEN}
    flex_query_id_trades: ${IBKR_FLEX_QUERY_ID_TRADES}
    flex_query_id_activity: ${IBKR_FLEX_QUERY_ID_ACTIVITY}
  return_data_only: True
```

`.env/apps.env`:

```env
IBKR_FLEX_TOKEN=
IBKR_FLEX_QUERY_ID_TRADES=
IBKR_FLEX_QUERY_ID_ACTIVITY=     # optional
```

**Creating them (Client Portal → Performance & Reports → Flex Queries):**
1. Create a **Trade Confirmation Flex Query**: all fields, format **XML**, period covering today,
   default date/time formats. Note the **Query ID**.
2. Optional — create an **Activity Flex Query**: section **Trades** with **Execution** detail (and
   **Cash Transactions** → **Deposits & Withdrawals** for deposits), all fields, format **XML**, period **Last 7 Calendar Days**. Trade Confirmation queries only allow
   **Today**; the Activity query adds a rolling week (available after IBKR's end-of-day processing)
   for backfills and missed runs. Note its **Query ID**.
3. In **Flex Web Service Configuration**, enable the service and generate a token. Note its expiry.

## Available Services

| Service | Method | Description |
|---|---|---|
| `ApiServiceIbkrFlex` | `send_request(query_id, from_date=None, to_date=None)` | Start generating a Flex Query report (`fd`/`td` override the saved period); returns the reference code |
| | `get_statement(reference)` | Download the report XML, retrying while it is still generating (code 1019) |
| | `get_statement_for_query(query_id=None, from_date=None, to_date=None)` | `send_request` + `get_statement`; optional `YYYYMMDD` range overrides the saved period |
| | `get_statements_for_range(query_id, from_date, to_date)` | One statement per ≤ 365-day chunk of a `YYYYMMDD` range |
| | `get_trades(query_id=None, from_date=None, to_date=None)` | Report parsed into `DtoIbkrTrade` executions (defaults to the trades query); optional range |
| | `get_cash_transactions(query_id=None, from_date=None, to_date=None)` | Report parsed into `DtoIbkrCashTransaction` rows (deposits, withdrawals, dividends, …); optional range |

Module helpers in `flex.py`: `date_ranges(start, end)`, `parse_trades(xml)`, `parse_cash_transactions(xml)`, `parse_flex_status(xml)`, `parse_flex_datetime(value)`.
`<TradeConfirm>` and execution-level Activity `<Trade>` rows are both supported; `trade_id` is the
`tradeID` (present in both report types), falling back to the execution ID.

## MCP Tools

| Tool | Args | Description |
|---|---|---|
| `get_ibkr_trades` | `asset_category?`, `from_date?`, `to_date?`, `query_id?` | Executions from the Flex Query, optionally filtered by asset category (e.g. `STK`). `from_date`/`to_date` (`YYYY-MM-DD`) fetch any historical range instead of the saved period; `to_date` defaults to today. Read-only. |
| `get_ibkr_cash_transactions` | `transaction_type?`, `from_date?`, `to_date?`, `query_id?` | Cash transactions from the Activity query (e.g. `Deposits/Withdrawals`), optionally for a date range ending yesterday at the latest. Read-only. |

## Tests

```sh
pytest apps/ibkr/tests/test_flex_parsing.py   # offline, no credentials
pytest apps/ibkr/tests/test_flex.py -m smoke   # live, needs IBKR_FLEX_TOKEN + IBKR_FLEX_QUERY_ID_TRADES
```

## Notes

- **Pacing:** `SendRequest` is limited to 1 request/second and 10 requests/minute per token; pacing rejections (1018) are retried after 10 seconds, up to 3 attempts.
- **Date ranges:** `fd`/`td` (YYYYMMDD) override a query's saved period, up to 365 days per request and only
  for days IBKR has processed (error 1003 for today or before the account existed). The saved period
  (e.g. Trade Confirmation = Today) only applies when no range is passed, so history needs no portal change.
  Verified live: the Trade Confirmation query serves past ranges and ranges ending today; the Activity
  query rejects ranges that include today (1003), so the cash tool caps `to_date` at yesterday.
- **User-Agent:** IBKR rejects requests without one; the base service always sends it.
- **Timing:** trade confirmations appear shortly after execution; commissions are only final in the
  end-of-day Activity statement. Times are as reported by IBKR (no timezone conversion).
- **Token expiry:** Flex tokens expire on the date chosen when generating them — renew before then.
- Used by `workflows/finance` (`capture_ibkr_trades`) to capture trades into a local ledger; publishing to Google Sheets is a separate task.
