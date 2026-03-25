# AAA Equities

## Description

- [AAA Equities](https://aaa-equities.com.ph/) is a Philippine Stock Exchange (PSEI) online trading platform.
- Automation uses Selenium to log in, navigate the UI, and extract portfolio/order/market data.
- No public REST API — all data is scraped through the browser interface.

## Supported Automations

- [ ] webservices
- [X] browser
- [ ] desktop
- [ ] mobile
- [ ] internet of things

## Directory Structure

```
apps/aaa/
├── config.py
├── references/
│   ├── base_page.py            # Extends harqis-core BaseFixturePageObject
│   ├── constants/
│   │   ├── links.py            # SidebarNavigationLinks, AccountWidgetLinks enums
│   │   └── strings.py          # Lot-type suffixes and cleanup chars
│   ├── models/
│   │   ├── account.py
│   │   ├── orders.py
│   │   ├── portfolio.py
│   │   └── stock.py
│   └── pages/
│       ├── login.py
│       ├── account.py
│       ├── market.py
│       ├── orders.py
│       └── portfolio.py
└── tests/
    └── unit_tests.py           # unittest.TestCase style (not pytest-style)
```

## Constants

| Enum | Values |
|------|--------|
| `SidebarNavigationLinks` | `MARKET`, `TRADE`, `QUOTE`, `TOP_STOCKS`, `HEAT_MAP`, `NEWS`, `CHART`, `BROKER` |
| `AccountWidgetLinks` | `ORDER_LIST`, `PORTFOLIO`, `ACCOUNT_SUMMARY`, `ORDER_SEARCH` |

`strings.py` defines lot-type suffixes (`\`N` for normal lots, `\`O` for odd lots) and characters to strip from price strings.

## Configuration (`apps_config.yaml`)

```yaml
AAA:
  app_id: 'aaa'
  client: 'browser'
  parameters:
    base_url: 'https://aaa-equities.com.ph/'
  app_data:
    username: ${AAA_USERNAME}
    password: ${AAA_PASSWORD}
```

## How to Use

```python
from apps.aaa.references.pages.login import LoginPage
from apps.aaa.references.pages.portfolio import PortfolioPage
from apps.aaa.config import CONFIG

# Launch browser and log in
login = LoginPage(CONFIG)
login.navigate()
login.login()

# Navigate to portfolio
portfolio = PortfolioPage(CONFIG)
data = portfolio.get_holdings()
```

## Running Tests

AAA tests use `unittest.TestCase` (not pytest-style). Run with:

```sh
pytest apps/aaa/tests/unit_tests.py
```

## Notes

- Selenium requires a compatible WebDriver (ChromeDriver) on `PATH`.
- Login session is not persisted between runs — each test logs in fresh.
- Odd-lot vs normal-lot suffixes (`\`N`, `\`O`) are appended to order identifiers per the platform's convention.
