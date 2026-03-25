# Investagrams

## Description

- [Investagrams](https://www.investagrams.com/) is a Philippine Stock Exchange (PSEI) analytics and stock screening platform.
- Data is extracted via BeautifulSoup and Selenium since no public REST API is available.
- Intended for screener data extraction and stock analytics — currently a stub with no implementation.

## Supported Automations

- [ ] webservices
- [X] browser
- [ ] desktop
- [ ] mobile
- [ ] internet of things

## Directory Structure

```
apps/investagrams/
├── references/
│   └── __init__.py             # Empty — no implementation yet
└── tests/
    └── __init__.py
```

## Status

This app is a **stub** — directory structure exists but no page objects, services, or tests are implemented.

## Planned Approach

When implemented, this app should follow the Selenium page object pattern used by `apps/aaa`:

```
apps/investagrams/
├── references/
│   ├── base_page.py            # Extends BaseFixturePageObject
│   ├── pages/
│   │   ├── login.py
│   │   └── screener.py
│   └── dto/
│       └── stock.py
└── tests/
```

## Notes

- Investagrams requires a registered account for access to screener tools.
- The platform uses heavy JavaScript rendering — Selenium is preferred over BeautifulSoup for dynamic content.
- No workflow tasks consume this app.
