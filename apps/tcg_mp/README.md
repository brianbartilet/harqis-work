# TCG Marketplace

## Description

- [The TCG Marketplace](https://thetcgmarketplace.com/) is a platform for buying and selling trading card game cards.
- This is the most complex app integration in HARQIS-work, supporting the full card resale pipeline.
- Provides REST API access for product search, listing management, order tracking, and pricing.
- Focused on Magic: The Gathering (category ID 3).

## Supported Automations

- [X] webservices
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] internet of things

## API Services

| Class | File | Methods |
|-------|------|---------|
| `ApiServiceTcgMpUserViewCart` | `web/api/cart.py` | `get_account_summary()` |
| `ApiServiceTcgMpMerchant` | `web/api/merchant.py` | `set_listing_status(listing_id, status)` |
| `ApiServiceTcgMpOrder` | `web/api/order.py` | `get_orders()`, `get_order_detail(id)`, `get_order_qr_code(id)` |
| `ApiServiceTcgMpProducts` | `web/api/product.py` | `search_card(name)`, `get_single_card(id)`, `search_single_card_listings(id)` |
| `ApiServiceTcgMpPublish` | `web/api/publish.py` | `add_listing(data)`, `edit_listing(id, data)`, `remove_listings(ids)` |
| `ApiServiceTcgMpUserView` | `web/api/view.py` | `get_listings()` |

## DTOs

| Class | File | Description |
|-------|------|-------------|
| `ListingStatus` | `dto/listing.py` | Enum for listing states |
| `DtoOrderSummaryByStatus`, `EnumTcgOrderStatus` | `dto/order.py` | Order data and status enum |
| `DtoCardData` | `dto/product.py` | Card product data |
| `DtoFilterResult` | `dto/search.py` | Search result filter |

## Configuration (`apps_config.yaml`)

```yaml
TCG_MP:
  app_id: 'tcg_mp'
  client: 'rest'
  parameters:
    base_url: 'https://thetcgmarketplace.com:3501/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 60
    stream: True
  app_data:
    category_id: 3          # Magic: The Gathering
    user_id: ${TCG_MP_USER_ID}
    username: ${TCG_MP_USERNAME}
    password: ${TCG_MP_PASSWORD}
    save_path: ${TCG_SAVE}
  return_data_only: True
```

`.env/apps.env`:

```env
TCG_MP_USER_ID=
TCG_MP_USERNAME=
TCG_MP_PASSWORD=
TCG_SAVE=/path/to/save/folder
```

## How to Use

### Search for a card

```python
from apps.tcg_mp.references.web.api.product import ApiServiceTcgMpProducts

svc = ApiServiceTcgMpProducts()
results = svc.search_card('Black Lotus')
listings = svc.search_single_card_listings(results[0].id)
```

### Manage listings

```python
from apps.tcg_mp.references.web.api.publish import ApiServiceTcgMpPublish

svc = ApiServiceTcgMpPublish()
svc.add_listing(listing_data)
svc.edit_listing(listing_id, updated_data)
svc.remove_listings([listing_id_1, listing_id_2])
```

### Check orders

```python
from apps.tcg_mp.references.web.api.order import ApiServiceTcgMpOrder

svc = ApiServiceTcgMpOrder()
orders = svc.get_orders()
detail = svc.get_order_detail(orders[0].id)
```

## Workflow Integration

This app is consumed by the `purchases` workflow for the full card resale pipeline:

1. `download_scryfall_bulk_data` — Download Scryfall card database (monthly)
2. `generate_tcg_listings` — Create new listings from inventory
3. `update_tcg_listings_prices` — Update listing prices (2am and noon daily)
4. `generate_audit_for_tcg_orders` — Audit pending orders (every 4 hours)

## Notes

- Authentication uses username/password login — token is cached after the first call in `BaseApiServiceAppTcgMp`.
- Worker functions in `tcg_mp_selling.py` re-import all dependencies inside the function body — required for `multiprocessing` on Windows (no `fork` support).
- `generate_tcg_mappings` is commented out in `purchases/tasks_config.py` — must be triggered manually or via n8n.
- `logger.warn()` (deprecated) is used in `tcg_mp_selling.py` — should be `logger.warning()`.
