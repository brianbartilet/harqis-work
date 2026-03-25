# Echo MTG

## Description

- [Echo MTG](https://www.echomtg.com/) is a Magic: The Gathering collection inventory management platform.
- Provides a [REST API](https://www.echomtg.com/api/) for automating inventory queries, card lookups, and note management.
- Used in the `purchases` workflow to match owned cards against TCG Marketplace listings.

## Supported Automations

- [X] webservices
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] internet of things

## API Services

| Class | File | Methods |
|-------|------|---------|
| `ApiServiceEchoMTGInventory` | `web/api/inventory.py` | `get_quick_stats()`, `get_collection(start, limit, sort, direction, tradable_only)`, `search_card(emid, tradable_only)` |
| `ApiServiceEchoMTGCardItem` | `web/api/item.py` | `get_card_meta(emid)` |
| `ApiServiceEchoMTGNotes` | `web/api/notes.py` | `get_note(id)`, `create_note(inventory_id, note)`, `update_note(id, note)`, `delete_note(id)` |

## DTOs

| Class | File | Description |
|-------|------|-------------|
| `DtoEchoMTGCard` | `dto/card.py` | Card data from inventory |
| `DtoPortfolioStats` | `dto/inventory.py` | Quick stats summary (value, count, etc.) |
| `DtoNotesInfo` | `dto/notes_info.py` | Note record |

## Configuration (`apps_config.yaml`)

```yaml
ECHO_MTG:
  app_id: 'echo_mtg'
  client: 'rest'
  parameters:
    base_url: 'https://www.echomtg.com/api/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 60
    stream: True
  app_data:
    email: ${ECHO_MTG_USER}
    password: ${ECHO_MTG_PASSWORD}
  return_data_only: True

ECHO_MTG_BULK:
  app_id: 'echo_mtg_bulk'
  client: 'rest'
  parameters:
    base_url: 'https://www.echomtg.com/api/'
  app_data:
    email: ${ECHO_MTG_BULK_USER}
    password: ${ECHO_MTG_BULK_PASSWORD}
    bearer_token: ${ECHO_MTG_BULK_BEARER_TOKEN}
  return_data_only: True
```

`.env/apps.env`:

```env
ECHO_MTG_USER=
ECHO_MTG_PASSWORD=
ECHO_MTG_BULK_USER=
ECHO_MTG_BULK_PASSWORD=
ECHO_MTG_BULK_BEARER_TOKEN=
```

## How to Use

```python
from apps.echo_mtg.references.web.api.inventory import ApiServiceEchoMTGInventory
from apps.echo_mtg.config import CONFIG

svc = ApiServiceEchoMTGInventory(CONFIG)

# Get portfolio stats
stats = svc.get_quick_stats()

# Get full collection (paginated, default 10,000 items)
cards = svc.get_collection()

# Search by Echo MTG ID
results = svc.search_card(emid='12345', tradable_only=1)
```

```python
from apps.echo_mtg.references.web.api.notes import ApiServiceEchoMTGNotes
from apps.echo_mtg.config import CONFIG

notes = ApiServiceEchoMTGNotes(CONFIG)
notes.create_note(inventory_id='67890', note='Listed on TCG Marketplace')
```

## Notes

- Authentication is email/password — token is acquired automatically on first call via `BaseApiServiceAppEchoMtg.authenticate()`.
- The bulk account (`ECHO_MTG_BULK_*`) is used for high-volume listing operations in the `purchases` workflow.
- `search_card` uses the Echo MTG internal ID (`emid`), not the card name.
