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
| `ApiServiceScryfallCards` | `web/api/cards.py` | `get_card_metadata(card_name)` |
| `ApiServiceScryfallBulkData` | `web/api/bulk.py` | `get_card_data_bulk()`, `download_bulk_file(uri, filename)` |

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

svc = ApiServiceScryfallCards()
card = svc.get_card_metadata('Black Lotus')
```

### Download bulk card data

```python
from apps.scryfall.references.web.api.bulk import ApiServiceScryfallBulkData

svc = ApiServiceScryfallBulkData()
bulk_info = svc.get_card_data_bulk()          # Lists available bulk files
svc.download_bulk_file(bulk_info.uri, 'all_cards.json')
```

Bulk data is used by the `purchases` workflow to match owned cards against market listings.

## Notes

- No API key required — Scryfall is a public API.
- The `app_name_header` is sent as a `User-Agent` header per Scryfall's API guidelines.
- Bulk data files can be hundreds of MB; the download path must have sufficient disk space.
- The `purchases/tasks/` workflow task `download_scryfall_bulk_data` runs on the 1st of each month at 2am.
