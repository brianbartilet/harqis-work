# AppSheet

AppSheet API v2 integration — query and mutate rows in any AppSheet table.
Primary use case is reading data from existing AppSheet apps; Add/Edit/Delete
are also supported.

- **API docs:** https://support.google.com/appsheet/answer/10105768
- **Auth:** per-app `ApplicationAccessKey` header (generated in the AppSheet
  app's *Manage → Integrations* tab; integrations must be enabled there first)
- **Base URL:** `https://api.appsheet.com/api/v2`

## Supported Automations

- [x] **webservices** — REST API client over httpx
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] iot

## Directory Structure

```
apps/appsheet/
├── __init__.py
├── config.py                     # loads APPSHEET section from apps_config.yaml
├── mcp.py                        # registers MCP tools
├── README.md
├── references/
│   ├── dto/
│   │   └── tables.py             # DtoAppSheetRow, DtoAppSheetActionResult
│   └── web/
│       ├── base_api_service.py   # ApplicationAccessKey header + _action() helper
│       └── api/
│           └── tables.py         # find / add / edit / delete rows
└── tests/
    └── test_tables.py
```

## Configuration

`apps_config.yaml`:

```yaml
APPSHEET:
  app_id: 'appsheet'
  client: 'rest'
  parameters:
    base_url: 'https://api.appsheet.com/api/v2'
    response_encoding: 'utf-8'
    verify: True
    timeout: 60
    stream: False
  app_data:
    application_access_key: ${APPSHEET_APPLICATION_ACCESS_KEY}
    default_app_id: ${APPSHEET_DEFAULT_APP_ID}
    locale: 'en-US'
  return_data_only: True
```

`.env/apps.env`:

```env
APPSHEET_APPLICATION_ACCESS_KEY=
APPSHEET_DEFAULT_APP_ID=
```

The `application_access_key` is per-AppSheet-app — generate it in your
AppSheet app under *Manage → Integrations*, then enable the IN setting.
`default_app_id` is the app id shown in that same panel; tools accept an
explicit `app_id=...` argument so a single key can drive multiple apps.

## Available Services

| Service class | Methods | Purpose |
|---|---|---|
| `ApiServiceAppSheetTables` | `find_rows`, `add_rows`, `edit_rows`, `delete_rows` | Query and mutate rows in any table of the configured AppSheet app |

## MCP Tools

| Tool | Args | Returns |
|---|---|---|
| `appsheet_find_rows` | `table`, `selector?`, `app_id?` | List of row dicts (every column the table exposes) |
| `appsheet_add_rows` | `table`, `rows`, `app_id?` | List of inserted row dicts (with system columns filled in) |
| `appsheet_edit_rows` | `table`, `rows`, `app_id?` | List of updated row dicts |
| `appsheet_delete_rows` | `table`, `rows`, `app_id?` | `{deleted, raw}` |

`selector` is an AppSheet expression evaluated server-side, e.g.:

```
Filter("Tasks", [Status] = "Open")
Filter("Inventory", AND([Qty] > 0, [Active] = TRUE))
```

`rows` for Edit/Delete must include the table's key column(s) so AppSheet
can locate the target row.

**Example prompts:**
- *"Show me every open task in my AppSheet 'Tasks' table."*
- *"Find rows in 'Inventory' where Qty is greater than 0 using AppSheet."*
- *"Add a new row to 'Leads' with Name 'Acme' and Email 'hi@acme.com'."*
- *"Update the row in 'Tasks' where Id = 42 to set Status to 'Done'."*

## Tests

All tests are live integration tests — no mocking. They are skipped unless
the following env vars are set:

```env
APPSHEET_APPLICATION_ACCESS_KEY=...
APPSHEET_DEFAULT_APP_ID=...
APPSHEET_TEST_TABLE=<name of a table the key has Read access to>
```

```sh
pytest apps/appsheet/tests/ -m smoke
pytest apps/appsheet/tests/ -m sanity
```

## Notes

- Every AppSheet endpoint is a POST against `/apps/{appId}/tables/{tableName}/Action`.
  The verb is in the body (`Action: "Find" | "Add" | "Edit" | "Delete"`),
  not the path.
- The API is **eventually consistent** — newly inserted rows may take a few
  seconds to appear in `find_rows` results.
- Rate limits apply per AppSheet app; bulk writes should be chunked.
- The access key is **per-app**, not per-account. You'll generate one key
  per AppSheet app you want to drive from harqis-work; reuse the same
  `APPSHEET_APPLICATION_ACCESS_KEY` only across apps that share the same
  underlying AppSheet account/key, otherwise pass `app_id=` explicitly per call.
- Selectors must be valid AppSheet expressions. Wrap string literals in
  double quotes inside the expression.
