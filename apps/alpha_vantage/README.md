# Alpha Vantage

## Description

Wraps the [Alpha Vantage REST API](https://www.alphavantage.co/documentation/) — a free-to-use market data provider for stocks, FX, crypto, commodities, US economic indicators, news with sentiment, fundamentals, and 50+ technical indicators. Authentication is a single `apikey` query parameter passed on every request.

References to keep handy when extending this app:

- **API documentation** — https://www.alphavantage.co/documentation/ (canonical list of every `function=...` value and its parameters)
- **Official MCP server** — https://mcp.alphavantage.co/ (separate, hosted; this integration is the harqis-work native client, not a wrapper around that server)
- **Sign up for an API key** — https://www.alphavantage.co/support/#api-key

## Supported Automations

- [x] webservices — REST API calls
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] internet of things

## Directory Structure

```
apps/alpha_vantage/
├── __init__.py
├── config.py                   # Loads ALPHA_VANTAGE section from apps_config.yaml
├── mcp.py                      # FastMCP tool registrations
├── README.md
├── references/
│   ├── dto/
│   │   ├── fundamentals.py     # DtoAlphaVantageCompanyOverview
│   │   ├── fx.py               # DtoAlphaVantageExchangeRate
│   │   ├── news.py             # DtoAlphaVantageNewsArticle, sentiment, topics
│   │   └── quote.py            # DtoAlphaVantageGlobalQuote, symbol search match
│   └── web/
│       ├── base_api_service.py # BaseApiServiceAlphaVantage — apikey injection + _query()
│       └── api/
│           ├── core_stock.py     # quotes, intraday/daily/weekly/monthly, search, market status
│           ├── fx.py             # exchange rate, FX time series, convert_currency helper
│           ├── news.py           # news_sentiment, top movers, insider, analytics
│           ├── fundamentals.py   # overview, ETF profile, statements, earnings, calendars
│           ├── technicals.py     # SMA, EMA, RSI, MACD, BBANDS + generic indicator dispatcher
│           ├── crypto.py         # crypto intraday/daily/weekly/monthly
│           ├── commodities.py    # WTI, BRENT, COPPER, ALUMINUM, WHEAT, etc.
│           └── economic.py       # GDP, treasury yield, fed funds, CPI, unemployment, …
└── tests/
    ├── test_core_stock.py
    ├── test_fx.py
    ├── test_news.py
    ├── test_fundamentals.py
    ├── test_technicals.py
    └── test_crypto.py
```

## Configuration

`apps_config.yaml`:

```yaml
ALPHA_VANTAGE:
  app_id: 'alpha_vantage'
  client: 'rest'
  parameters:
    base_url: 'https://www.alphavantage.co/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 60
    stream: False
  app_data:
    api_key: ${ALPHA_VANTAGE_API_KEY}
  return_data_only: True
```

`.env/apps.env`:

```env
ALPHA_VANTAGE_API_KEY=your_key_here
```

## Available Services

| Service class | Module | Purpose |
|---|---|---|
| `ApiServiceAlphaVantageCoreStock` | `references/web/api/core_stock.py` | Latest quote, time series (intraday/daily/weekly/monthly, raw + adjusted), bulk quotes, symbol search, market status |
| `ApiServiceAlphaVantageFx` | `references/web/api/fx.py` | Exchange rate, FX intraday/daily/weekly/monthly, `convert_currency()` helper |
| `ApiServiceAlphaVantageNews` | `references/web/api/news.py` | News & sentiment, top gainers/losers, insider transactions, earnings transcript, analytics windows |
| `ApiServiceAlphaVantageFundamentals` | `references/web/api/fundamentals.py` | Company overview, ETF profile, dividends, splits, income/balance/cash-flow statements, earnings, calendars |
| `ApiServiceAlphaVantageTechnicals` | `references/web/api/technicals.py` | Generic `get_indicator(function, ...)` dispatcher + named helpers (SMA, EMA, RSI, MACD, BBANDS, ADX, ATR, STOCH, OBV) |
| `ApiServiceAlphaVantageCrypto` | `references/web/api/crypto.py` | Crypto intraday + daily/weekly/monthly digital currency series |
| `ApiServiceAlphaVantageCommodities` | `references/web/api/commodities.py` | WTI, BRENT, NATURAL_GAS, COPPER, ALUMINUM, WHEAT, CORN, COTTON, SUGAR, COFFEE, ALL_COMMODITIES |
| `ApiServiceAlphaVantageEconomic` | `references/web/api/economic.py` | REAL_GDP, REAL_GDP_PER_CAPITA, TREASURY_YIELD, FEDERAL_FUNDS_RATE, CPI, INFLATION, RETAIL_SALES, DURABLES, UNEMPLOYMENT, NONFARM_PAYROLL |

## MCP Tools

See [`mcp.py`](mcp.py) for the full list. Key tools:

| Tool | Description |
|---|---|
| `alpha_vantage_global_quote` | Latest price/volume for a single ticker |
| `alpha_vantage_realtime_bulk_quotes` | Realtime quotes for up to 100 tickers in one call |
| `alpha_vantage_search_symbol` | Symbol search by company name |
| `alpha_vantage_market_status` | Open/closed status for global venues |
| `alpha_vantage_time_series_intraday` / `_daily` | OHLCV time series |
| `alpha_vantage_fx_rate` | Realtime FX rate (also accepts crypto codes) |
| `alpha_vantage_convert_currency` | Convert an amount between two currencies |
| `alpha_vantage_fx_intraday` / `_daily` | FX time series |
| `alpha_vantage_news_sentiment` | News articles with per-article sentiment |
| `alpha_vantage_top_gainers_losers` | Daily top movers |
| `alpha_vantage_insider_transactions` | Insider buys/sells |
| `alpha_vantage_company_overview` | Description, ratios, market cap |
| `alpha_vantage_income_statement` / `_balance_sheet` / `_cash_flow` / `_earnings` / `_dividends` | Fundamentals |
| `alpha_vantage_indicator` | Generic technical indicator dispatcher |
| `alpha_vantage_rsi` / `_sma` / `_ema` / `_macd` / `_bbands` | Common technical indicators |
| `alpha_vantage_crypto_intraday` / `_daily` | Crypto time series |
| `alpha_vantage_commodity` | Commodity prices (WTI, BRENT, …) |
| `alpha_vantage_economic_indicator` | US economic indicators (GDP, CPI, …) |

## Adding a new endpoint

The full Alpha Vantage surface is much larger than what we wrap by default. Adding a new endpoint is intentionally cheap:

1. Look up the new function on https://www.alphavantage.co/documentation/ — note the `function=` value and its parameters.
2. Pick the matching service file in `references/web/api/` (or create a new one for a new category).
3. Add a method that calls `self._query('FUNCTION_NAME', **params)`. The base class handles `apikey`, JSON content type, the `/query` path, and per-call URL reset.
4. Optionally expose it as an MCP tool by adding a `@mcp.tool()` wrapper in `mcp.py`.

For technical indicators specifically, you usually do not need to add anything — `ApiServiceAlphaVantageTechnicals.get_indicator(function, symbol, **kwargs)` already accepts arbitrary indicator function names.

## Tests

```sh
pytest apps/alpha_vantage/tests/
pytest apps/alpha_vantage/tests/ -m smoke
```

All tests are live and require a valid `ALPHA_VANTAGE_API_KEY`.

## Notes

- **Rate limits.** The free tier is 25 requests/day. Premium tiers (50/min and up) raise the cap — see https://www.alphavantage.co/premium/. Beat the limit and the API returns a JSON note rather than an HTTP error, so service responses can include a `"Note"` or `"Information"` key instead of the requested data.
- **CSV responses.** A few endpoints (`LISTING_STATUS`, `EARNINGS_CALENDAR`, `IPO_CALENDAR`) return CSV by default. Pass `datatype='json'` where supported, or parse the raw text.
- **Free-form JSON.** Most time series responses use date-keyed dicts (e.g. `Time Series (Daily)`), so the service methods return raw `dict` rather than typed DTOs. Typed DTOs are provided only for fixed-shape responses like `GLOBAL_QUOTE`, `CURRENCY_EXCHANGE_RATE`, `OVERVIEW`, and `NEWS_SENTIMENT`.
