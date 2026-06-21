# Scryfall

## Description

- [Scryfall](https://scryfall.com/) is the most comprehensive Magic: The Gathering card database.
- Provides a [public REST API](https://scryfall.com/docs/api) with no authentication required for most endpoints.
- Used to look up card metadata and download bulk card data for offline processing in the TCG resale pipeline.

## Supported Automations

- [X] webservices
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] internet of things

## API Services

| Class | File | Methods |
|-------|------|---------|
| `ApiServiceScryfallCards` | `web/api/cards.py` | `get_card_metadata(guid)`, `get_card_raw(guid)`, `get_card_by_name(name, set_code=None, fuzzy=True)`, `get_card_versions(name)` |
| `ApiServiceScryfallBulkData` | `web/api/bulk.py` | `get_card_data_bulk()`, `download_bulk_file(type)`, `query_bulk(query, bulk_data_type, field, limit, force_download)` |

## MCP Tools

Registered by `register_scryfall_tools` in `apps/scryfall/mcp.py`:

| Tool | Description |
|------|-------------|
| `get_scryfall_card` | Full card metadata by Scryfall UUID |
| `get_scryfall_bulk_data_info` | List available bulk data files (no download) |
| `get_scryfall_card_prices` | Card prices by UUID **or** name |
| `get_scryfall_card_images` | Card image URIs by UUID **or** name (handles double-faced cards) |
| `get_scryfall_card_versions` | All prints/versions of a card by name (or UUID, resolved to name first) |
| `query_scryfall_bulk` | Download (or reuse) latest bulk file and stream-filter matching cards |

## Configuration (`apps_config.yaml`)

```yaml
SCRYFALL:
  app_id: 'scry_mtg'
  client: 'rest'
  parameters:
    base_url: 'https://api.scryfall.com/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 60
    stream: True
  return_data_only: True
  app_data:
    app_name_header: 'harqis-work/1.0'
    path_folder_static_file: ${SCRY_DOWNLOADS_PATH}
```

`.env/apps.env`:

```env
SCRY_DOWNLOADS_PATH=/path/to/downloads/folder
```

## How to Use

### Look up a card

```python
from apps.scryfall.references.web.api.cards import ApiServiceScryfallCards
from apps.scryfall.config import CONFIG

svc = ApiServiceScryfallCards(CONFIG)
card = svc.get_card_metadata('e3285e6b-3e79-4d7c-bf96-d920f973b122')  # by UUID
card = svc.get_card_by_name('Black Lotus')                            # by name (fuzzy)
versions = svc.get_card_versions('Sol Ring')                         # all prints
```

### Download bulk card data

```python
from apps.scryfall.references.web.api.bulk import ApiServiceScryfallBulkData
from apps.scryfall.config import CONFIG

svc = ApiServiceScryfallBulkData(CONFIG)
bulk_info = svc.get_card_data_bulk()                 # Lists available bulk files
svc.download_bulk_file('all-cards')                  # Download full file

# Stream-filter the latest bulk file without loading it all into memory
matches = svc.query_bulk('Lightning Bolt', bulk_data_type='default-cards', field='name', limit=20)
```

Bulk data is used by the `purchases` workflow to match owned cards against market listings.

## Notes

- No API key required — Scryfall is a public API.
- The `app_name_header` is sent as a `User-Agent` header per Scryfall's API guidelines.
- Bulk data files can be hundreds of MB; the download path must have sufficient disk space.
- The `purchases/tasks/` workflow task `download_scryfall_bulk_data` runs on the 1st of each month at 2am.
