# Notion

## Description

- [Notion](https://www.notion.so/) is an all-in-one workspace for notes, databases, tasks, and wikis.
- REST API documentation: [Notion API](https://developers.notion.com/reference/intro)
- Authorization guide: [Notion Authorization](https://developers.notion.com/docs/authorization)
- Integrates pages, databases, blocks, users, and search into HARQIS workflows.

## Supported Automations

- [X] webservices
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] internet of things

## Directory Structure

```
apps/notion/
├── config.py
├── mcp.py                              # 11 MCP tools
├── references/
│   ├── dto/
│   │   └── notion.py                  # DtoNotionPage, DtoNotionDatabase, DtoNotionBlock, DtoNotionUser
│   └── web/
│       ├── base_api_service.py        # Injects Bearer token + Notion-Version header
│       └── api/
│           ├── databases.py           # get_database, query_database, create_database, update_database
│           ├── pages.py               # get_page, get_page_property, create_page, update_page
│           ├── blocks.py              # get_block, get_block_children, append_block_children, update_block, delete_block
│           ├── users.py               # get_me, get_user, list_users
│           └── search.py              # search
└── tests/
    ├── test_databases.py
    ├── test_pages.py
    ├── test_users.py
    └── test_search.py
```

## Authentication

Notion uses an **Integration Token** (Bearer) passed in the `Authorization` header on every request.
A `Notion-Version` header is also required.

```
Authorization: Bearer ntn_xxxxxxxxxxxx
Notion-Version: 2022-06-28
```

### Step 1 — Create an Internal Integration

1. Go to **https://www.notion.so/my-integrations**
2. Click **+ New integration**
3. Give it a name (e.g. `harqis-work`)
4. Select the workspace you want to connect
5. Under **Capabilities**, enable **Read content**, **Update content**, and **Insert content**
6. Click **Submit**
7. Copy the **Internal Integration Token** (starts with `ntn_` or `secret_`) — this is your `NOTION_API_TOKEN`

### Step 2 — Share pages/databases with the integration

Notion uses a permission model where you must explicitly share each page or database with your integration:

1. Open any Notion page or database
2. Click **...** (top-right) → **Connections** → find your integration → **Confirm**

The integration can now access that page and all its children.

### Step 3 — Add to `.env/apps.env`

```bash
# Notion
NOTION_API_TOKEN=ntn_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## Configuration (`apps_config.yaml`)

```yaml
NOTION:
  app_id: 'notion'
  client: 'rest'
  parameters:
    base_url: 'https://api.notion.com/v1/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 60
    stream: True
  app_data:
    api_token: ${NOTION_API_TOKEN}
  return_data_only: True
```

---

## Available Services

### Databases (`references/web/api/databases.py`)

| Method | Args | Returns |
|--------|------|---------|
| `get_database(database_id)` | `database_id` | Database metadata and property schema |
| `query_database(database_id, filter?, sorts?, page_size?)` | `database_id` required | Paginated pages in database |
| `create_database(parent_page_id, title, properties?)` | `parent_page_id`, `title` required | New database |
| `update_database(database_id, title?, properties?)` | `database_id` required | Updated database |

### Pages (`references/web/api/pages.py`)

| Method | Args | Returns |
|--------|------|---------|
| `get_page(page_id)` | `page_id` | Page metadata and properties |
| `get_page_property(page_id, property_id)` | `page_id`, `property_id` | Single property value |
| `create_page(parent, properties, children?, icon?, cover?)` | `parent`, `properties` required | New page |
| `update_page(page_id, properties?, archived?, icon?, cover?)` | `page_id` required | Updated page |

### Blocks (`references/web/api/blocks.py`)

| Method | Args | Returns |
|--------|------|---------|
| `get_block(block_id)` | `block_id` | Single block |
| `get_block_children(block_id, page_size?)` | `block_id` | Paginated child blocks |
| `append_block_children(block_id, children)` | `block_id`, `children` required | Updated block list |
| `update_block(block_id, block_type, content)` | all required | Updated block |
| `delete_block(block_id)` | `block_id` | Archived block |

### Users (`references/web/api/users.py`)

| Method | Args | Returns |
|--------|------|---------|
| `get_me()` | — | Bot user profile |
| `get_user(user_id)` | `user_id` | Any user's profile |
| `list_users(page_size?)` | — | All workspace users |

### Search (`references/web/api/search.py`)

| Method | Args | Returns |
|--------|------|---------|
| `search(query?, filter_object?, sort_direction?, page_size?)` | all optional | Matching pages and databases |

---

## MCP Tools

Registered in `mcp/server.py` as `harqis-mcp.notion`. Available tools:

| Tool | Description |
|------|-------------|
| `get_notion_database` | Retrieve a database by ID |
| `query_notion_database` | Query pages in a database with optional filter/sort |
| `create_notion_database` | Create a new inline database under a page |
| `get_notion_page` | Retrieve a page by ID |
| `create_notion_page` | Create a page in a database or as a sub-page |
| `update_notion_page` | Update page properties or archive it |
| `get_notion_block_children` | List all child blocks of a page or block |
| `append_notion_block_children` | Append new blocks to a page or block |
| `get_notion_me` | Get the bot user for the current integration |
| `list_notion_users` | List all workspace users |
| `search_notion` | Search pages and databases by query or type |

---

## Running Tests

```sh
# All Notion tests
pytest apps/notion/tests/

# Smoke tests only
pytest apps/notion/tests/ -m smoke

# Sanity tests only
pytest apps/notion/tests/ -m sanity
```

All tests are live integration tests — a valid `NOTION_API_TOKEN` in `.env/apps.env` is required,
and at least one page or database must be shared with the integration.
