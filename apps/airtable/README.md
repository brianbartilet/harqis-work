# Airtable

Airtable Web API integration — bases, tables, fields, and full record CRUD with
formula filters, sorting, pagination, and upsert.

- **API docs:** https://airtable.com/developers/web/api/introduction
- **Auth:** Bearer Personal Access Token — `Authorization: Bearer ${AIRTABLE_API_TOKEN}`
- **Base URL:** `https://api.airtable.com/v0`

## Supported Automations

- [x] **webservices** — REST API client over httpx
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] iot

## Directory Structure

```
apps/airtable/
├── __init__.py
├── config.py                     # loads AIRTABLE section from apps_config.yaml
├── mcp.py                        # registers MCP tools
├── README.md
├── references/
│   ├── dto/
│   │   ├── bases.py              # DtoAirtableBase, DtoAirtableUser
│   │   ├── records.py            # DtoAirtableRecord, DtoAirtableRecordsPage
│   │   └── tables.py             # DtoAirtableTable, DtoAirtableField, DtoAirtableView
│   └── web/
│       ├── base_api_service.py   # Bearer-token httpx helpers
│       └── api/
│           ├── bases.py          # /meta/bases, /meta/whoami
│           ├── records.py        # /{baseId}/{table} CRUD + pagination + upsert
│           └── tables.py         # /meta/bases/{baseId}/tables, /fields
└── tests/
    └── test_airtable.py
```

## Configuration

`apps_config.yaml`:
```yaml
AIRTABLE:
  app_id: 'airtable'
  client: 'rest'
  parameters:
    base_url: 'https://api.airtable.com/v0'
    response_encoding: 'utf-8'
    verify: True
    timeout: 30
    stream: False
  app_data:
    api_token: ${AIRTABLE_API_TOKEN}
  return_data_only: True
```

`.env/apps.env`:
```
AIRTABLE_API_TOKEN=<personal access token from https://airtable.com/create/tokens>
```

The PAT must have at minimum `data.records:read`/`write` and `schema.bases:read`
scopes plus access to the specific bases you want to use.

## Available Services

| Service class | Methods | Purpose |
|---|---|---|
| `ApiServiceAirtableBases` | `list_bases`, `whoami` | Discovery — list bases, who am I |
| `ApiServiceAirtableTables` | `list_tables`, `create_table`, `update_table`, `create_field`, `update_field` | Schema introspection + mutation |
| `ApiServiceAirtableRecords` | `list_records`, `list_all_records`, `get_record`, `create_records`, `update_records`, `upsert_records`, `delete_records` | Record CRUD + auto-pagination + upsert |

## MCP Tools

| Tool | Args | Returns |
|---|---|---|
| `airtable_whoami` | — | `{id, email, scopes}` |
| `airtable_list_bases` | — | List of `{id, name, permissionLevel}` |
| `airtable_list_tables` | `base_id` | List of tables with their fields and views |
| `airtable_list_records` | `base_id`, `table`, `view?`, `filter_by_formula?`, `max_records?`, `page_size?`, `sort?`, `fields?`, `offset?` | `{records, offset, count}` (one page) |
| `airtable_list_all_records` | `base_id`, `table`, `view?`, `filter_by_formula?`, `max_records?`, `sort?`, `fields?` | All matching records (auto-paginated) |
| `airtable_get_record` | `base_id`, `table`, `record_id` | `{id, createdTime, fields}` |
| `airtable_create_records` | `base_id`, `table`, `records`, `typecast?` | List of created records (max 10) |
| `airtable_update_records` | `base_id`, `table`, `records`, `typecast?`, `replace?` | List of updated records (max 10) |
| `airtable_upsert_records` | `base_id`, `table`, `records`, `merge_on`, `typecast?` | Raw API response |
| `airtable_delete_records` | `base_id`, `table`, `record_ids` | Raw API response |
| `airtable_create_table` | `base_id`, `name`, `fields`, `description?` | Created table dict |
| `airtable_create_field` | `base_id`, `table_id`, `name`, `type`, `options?`, `description?` | Created field dict |

**Example prompts:**
- *"List all my Airtable bases."*
- *"Show me the first 10 records in base appXYZ table 'Tasks' where Status is Done."*
- *"Create a new record in base appXYZ table 'Leads' with Name='Acme' and Email='hi@acme.com'."*
- *"Add a singleSelect field 'Priority' with options Low/Medium/High to table tblABC in base appXYZ."*

## Tests

All tests are live integration tests — no mocking. They use the first base
visible to the PAT, so set `AIRTABLE_API_TOKEN` and ensure the PAT has at
least one base with read access.

```sh
pytest apps/airtable/tests/ -m smoke
pytest apps/airtable/tests/ -m sanity
```

## Notes

- **Personal Access Tokens** are the recommended auth method (legacy API keys
  are deprecated). Generate one at https://airtable.com/create/tokens with
  the scopes and base access you need.
- **Rate limit:** 5 requests/second per base. The API returns HTTP 429 if exceeded
  and you must wait 30 seconds before sending more.
- **Pagination:** `list_records` returns up to 100 rows + an `offset` token.
  Use `list_all_records` to auto-paginate through every page.
- **Bulk writes:** create/update/upsert/delete are capped at **10 records per call**.
  For larger batches, chunk client-side.
- **Table can be id or name:** all record endpoints accept either `tblXXXX...`
  ids or human-readable table names. Names are URL-encoded automatically.
- **Typecast:** when sending data as strings (e.g. from a form), pass
  `typecast=True` so Airtable coerces them to the field type.
- **Upsert:** `airtable_upsert_records` matches existing rows on the
  `merge_on` field values. New rows are created if no match is found.
