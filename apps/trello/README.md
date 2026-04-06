# Trello

## Description

- [Trello](https://trello.com/) is a web-based Kanban board application (Atlassian).
- REST API documentation: [Trello REST API](https://developer.atlassian.com/cloud/trello/rest/)
- Authorization guide: [Trello REST API Authorization](https://developer.atlassian.com/cloud/trello/guides/rest-api/authorization/)
- Integrates boards, lists, cards, and members into HARQIS workflows.

## Supported Automations

- [X] webservices
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] internet of things

## Directory Structure

```
apps/trello/
├── config.py
├── mcp.py                              # 10 MCP tools
├── references/
│   ├── dto/
│   │   └── board.py                   # DtoTrelloBoard, DtoTrelloList, DtoTrelloCard, DtoTrelloMember
│   └── web/
│       ├── base_api_service.py        # Injects API key + token as query params
│       └── api/
│           ├── boards.py              # get_my_boards, get_board, get_board_lists, get_board_cards, create_board, archive_board
│           ├── cards.py               # get_card, get_list_cards, create_card, update_card, archive_card, move_card
│           └── members.py             # get_me, get_member, get_member_boards, get_board_members
└── tests/
    ├── test_boards.py
    ├── test_cards.py
    └── test_members.py
```

## Authentication

Trello uses **API Key + Token** passed as query parameters on every request:

```
https://api.trello.com/1/{resource}?key={TRELLO_API_KEY}&token={TRELLO_API_TOKEN}
```

### Step 1 — Get your API Key

1. Go to **https://trello.com/power-ups/admin**
2. Create a new Power-Up (or select an existing one)
3. Navigate to the **API Key** tab
4. Copy the **32-character API key** shown — this is your `TRELLO_API_KEY`

> The API key is tied to your Power-Up and is safe to treat as semi-public, but keep it out of source control.

### Step 2 — Generate a Token

On the same API Key page, click the **Token** hyperlink. This opens an authorization URL like:

```
https://trello.com/1/authorize?expiration=never&scope=read,write&response_type=token&name=harqis-work&key=YOUR_API_KEY
```

1. Log in to Trello if prompted
2. Click **Allow**
3. Copy the **64-character token** shown — this is your `TRELLO_API_TOKEN`

> The token grants access to your Trello data. Keep it secret — treat it like a password.

### Step 3 — Add to `.env/apps.env`

```bash
# Trello
TRELLO_API_KEY=<your 32-char key>
TRELLO_API_TOKEN=<your 64-char token>
```

---

## Configuration (`apps_config.yaml`)

```yaml
TRELLO:
  app_id: 'trello'
  client: 'rest'
  parameters:
    base_url: 'https://api.trello.com/1/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 60
    stream: True
  app_data:
    api_key: ${TRELLO_API_KEY}
    api_token: ${TRELLO_API_TOKEN}
  return_data_only: True
```

---

## Available Services

### Boards (`references/web/api/boards.py`)

| Method | Args | Returns |
|--------|------|---------|
| `get_my_boards()` | — | All boards for the authenticated member |
| `get_board(board_id)` | `board_id` | Single board details |
| `get_board_lists(board_id, filter?)` | `board_id`, `filter` ('open') | Lists on a board |
| `get_board_cards(board_id, filter?)` | `board_id`, `filter` ('open') | Cards on a board |
| `create_board(name, desc?, id_organization?)` | `name` required | New board |
| `archive_board(board_id)` | `board_id` | Close (archive) a board |

### Cards (`references/web/api/cards.py`)

| Method | Args | Returns |
|--------|------|---------|
| `get_card(card_id)` | `card_id` | Single card details |
| `get_list_cards(list_id, filter?)` | `list_id` | Cards in a list |
| `create_card(list_id, name, desc?, due?, id_members?, id_labels?)` | `list_id`, `name` required | New card |
| `update_card(card_id, ...)` | `card_id` + optional fields | Updated card |
| `archive_card(card_id)` | `card_id` | Close (archive) a card |
| `move_card(card_id, list_id)` | `card_id`, `list_id` | Move card to another list |

### Members (`references/web/api/members.py`)

| Method | Args | Returns |
|--------|------|---------|
| `get_me()` | — | Authenticated member profile |
| `get_member(member_id)` | `member_id` or username | Any member's profile |
| `get_member_boards(member_id?, filter?)` | defaults to 'me' | Boards for a member |
| `get_board_members(board_id)` | `board_id` | All members on a board |

---

## MCP Tools

Registered in `mcp/server.py` as `harqis-mcp.trello`. Available tools:

| Tool | Description |
|------|-------------|
| `get_trello_my_boards` | All boards for the authenticated member |
| `get_trello_board` | Single board by ID |
| `get_trello_board_lists` | Lists on a board |
| `get_trello_board_cards` | Cards on a board |
| `get_trello_list_cards` | Cards in a specific list |
| `get_trello_card` | Single card by ID |
| `create_trello_card` | Create a card in a list |
| `update_trello_card` | Update card fields |
| `get_trello_me` | Authenticated member profile |
| `get_trello_board_members` | Members on a board |

---

## Running Tests

```sh
# All Trello tests
pytest apps/trello/tests/

# Smoke tests only
pytest apps/trello/tests/ -m smoke

# Sanity tests only
pytest apps/trello/tests/ -m sanity
```

All tests are live integration tests — valid credentials in `.env/apps.env` are required.
