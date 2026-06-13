# MPC (MakePlayingCards.com)

## Description

Browser automation for [makeplayingcards.com](https://www.makeplayingcards.com/)'s custom
blank-card designer — a **Playwright port** of the Selenium driver in
[chilli-axe/mpc-autofill](https://github.com/chilli-axe/mpc-autofill) (desktop-tool). Given an
order of local card images, it signs in, configures a project (cardstock / quantity bracket /
foil), uploads every front through the site's file input, assigns images to slots via the
designer's own JS (`PageLayout.prototype.applyDragPhoto`), sets the shared cardback, and
**saves the project to the account**. It intentionally **never checks out** — the headed
browser is left open for manual review, add-to-cart, and payment.

Order files use mpc-autofill's XML schema (local-file variant), so they're interchangeable
with the upstream tool.

- **Auth:** MPC account credentials (auto-filled on `login.aspx`; falls back to waiting for a
  manual sign-in — detected via the logout link). An optional persistent Chromium profile dir
  keeps the session across runs.
- **Limits:** max **612 cards per project** (`build_orders` auto-splits); poker-size uploads
  should be **822×1122 px @ 300 DPI** (2.72"×3.7" incl. bleed).

## Supported Automations

- [ ] webservices
- [x] browser — Playwright (Chromium) page automation
- [ ] desktop
- [ ] mobile
- [ ] internet of things

## Directory Structure

```
apps/mpc/
├── __init__.py
├── config.py                          # Loads the MPC section from apps_config.yaml
├── mcp.py                             # FastMCP tool registrations (XML build/validate)
├── references/
│   ├── dto/
│   │   └── order.py                   # DtoMpcOrder/-CardImage/-OrderDetails + build_orders (≤612 split)
│   ├── xml/
│   │   └── order_xml.py               # mpc-autofill-compatible order XML read/write
│   └── web/
│       ├── constants.py               # MPC URLs, element ids, designer JS entry points
│       └── driver.py                  # MpcAutofillDriver — the Playwright autofill flow
└── tests/
    ├── test_order_xml.py              # offline: build/split/round-trip/pid/validate
    └── test_driver.py                 # live (opt-in: MPC_DRIVER_LIVE_TEST=1)
```

## Configuration

Add this section to `apps_config.yaml`:

```yaml
MPC:
  app_id: 'mpc'
  base_url: 'https://www.makeplayingcards.com'
  app_data:
    email: ${MPC_EMAIL}
    password: ${MPC_PASSWORD}
    user_data_dir: ${MPC_BROWSER_PROFILE_DIR}
```

And to `.env/apps.env`:

```env
MPC_EMAIL=
MPC_PASSWORD=
MPC_BROWSER_PROFILE_DIR=    # optional — persistent Chromium profile keeps the session
```

## Available Services

| Class / function | File | Purpose |
|------------------|------|---------|
| `MpcAutofillDriver` | `web/driver.py` | `launch()` · `authenticate()` · `execute_order(order, auto_save_threshold=5)` — full autofill ending saved-not-checked-out |
| `build_orders(image_paths, cardback_path, stock, foil, name_prefix)` | `dto/order.py` | Pack images one-per-slot into ≤612-card orders (auto-split) |
| `write_order_xml(order, path)` / `read_order_xml(path)` | `xml/order_xml.py` | mpc-autofill-compatible XML round-trip |
| `DtoMpcOrder.validate()` | `dto/order.py` | Slot coverage, files on disk, cardback, 612 cap |

## MCP Tools

| Tool | Args | Description |
|------|------|-------------|
| `build_mpc_order_xml` | `fronts_dir`, `cardback_path`, `output_path`, `stock?`, `name_prefix?` | Build order XML(s) from an image directory (auto-splits over 612) |
| `validate_mpc_order` | `xml_path` | Validate an order XML; returns summary + problem list |

The browser driver itself is deliberately **not** exposed over MCP — it is long-running,
headed, and account-mutating. Run it via `workflows/tcg` or pytest.

## Tests

```bash
pytest apps/mpc/tests/ -m smoke                          # offline XML/DTO tests
MPC_DRIVER_LIVE_TEST=1 pytest apps/mpc/tests/ -m integration   # live headed-browser checks
```

## Notes

- **Checkout is manual by design** (same as upstream): the run ends with the project in
  *Saved Projects* and the browser open.
- Auto-save fires every `auto_save_threshold` mutating inserts (default 5) via
  `oDesign.setTemporarySave()`, so an interrupted run resumes from the saved project.
- Image identity is the uppercase SHA-1 of file bytes ("pid") — re-running an order skips
  already-uploaded images and already-filled slots (idempotent).
- MPC project names cap at 32 characters; quantity brackets are read live from the site's
  dropdown (smallest bracket ≥ order size wins).
- The MPC designer is a legacy ASP.NET frontend — flows depend on its global JS objects
  (`oDesign`, `oDesignImage`, `PageLayout`); a site redesign would break this driver.
