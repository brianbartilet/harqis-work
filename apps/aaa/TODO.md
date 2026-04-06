# apps/aaa — TODO

## Planned Refactor: Hybrid Selenium + requests/BS4 Architecture

### Context
The current implementation uses Selenium WebDriver for all operations (login, account, portfolio, orders, market data).
The goal is to use `requests.Session` + BeautifulSoup for all read operations, keeping Selenium only for order submission.

### Why
- Browser startup per test adds 3-5s overhead
- XPath locators tied to CSS class names break on UI updates
- No session reuse — every page class re-authenticates
- `wait_page_to_load()` called 4-5x per action makes tests flaky
- `unit_tests.py` uses `unittest.TestCase` — needs to be converted to pytest

### Proposed Architecture
```
AAASession (requests.Session + cookie auth)
  - login() → Selenium once to capture cookies, then hands off to requests
  - get_account()    → HTTP GET + BS4 parse
  - get_portfolio()  → HTTP GET + BS4 parse
  - get_orders()     → HTTP GET + BS4 parse
  - get_market()     → HTTP GET + BS4 parse

PageAAATradingDeskOrders (Selenium — keep as-is)
  - create_order()   → Selenium only (form interaction required)
```

### Tasks

- [ ] `references/web/session.py` — `AAASession` class: `requests.Session` with cookie injection from Selenium post-login
- [ ] `references/web/api/account.py` — BS4 scraper replacing `PageAAATradingDeskAccount.get_account_information()`
- [ ] `references/web/api/portfolio.py` — BS4 scraper replacing `PageAAATradingDeskPortfolio.get_portfolio_information()`
- [ ] `references/web/api/orders.py` — BS4 scraper for reading orders (keep Selenium only for `create_order`)
- [ ] `references/web/api/market.py` — BS4 scraper replacing `PageAAATradingDeskMarket.get_instrument_market_info()`
- [ ] Convert `tests/unit_tests.py` to pytest style with fixtures and marks
- [ ] Add `AAA:` section to `apps_config.yaml` (currently missing)
- [ ] Add `APPEND_ODD_LOTS` support in `create_order` (only `APPEND_NORMAL_LOTS` used)

### Known Issues in Current Code
- `trades` and `cash_map` fields in `ModelStockAAA` are initialized but never populated
- `CLEAN_CHARS` is defined in `strings.py` but redefined locally in `portfolio.py`
- `test_create_order` in `unit_tests.py` is DEV-only (no guard/skip mark)
- `button_dialog_password_ok` catches `NoSuchElementException` but logs as error instead of debug
