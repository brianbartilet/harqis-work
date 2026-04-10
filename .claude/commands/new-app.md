Scaffold a new app integration under `apps/`.

The argument $ARGUMENTS is the new app name in snake_case (e.g. `stripe`, `notion`).

Steps:
1. Create the directory `apps/$ARGUMENTS/` with the standard structure:
   ```
   apps/<name>/
   ├── __init__.py
   ├── config.py
   ├── mcp.py
   ├── references/
   │   ├── __init__.py
   │   ├── dto/
   │   │   └── __init__.py
   │   └── web/
   │       ├── base_api_service.py
   │       └── api/
   │           └── __init__.py
   └── tests/
       └── __init__.py
   ```
2. Write `config.py` using the standard pattern:
   ```python
   import os
   from core.config.loader import ConfigLoaderService
   from core.web.services.core.config.webservice import AppConfigWSClient
   from core.config.env_variables import ENV_APP_CONFIG_FILE

   load_config = ConfigLoaderService(file_name=ENV_APP_CONFIG_FILE).config
   APP_NAME = str(os.path.basename(os.path.dirname(os.path.abspath(__file__)))).upper()
   CONFIG = AppConfigWSClient(**load_config[APP_NAME])
   ```
3. Write `references/web/base_api_service.py` inheriting from `BaseFixtureServiceRest`.
   Inject auth headers and any required API headers in `__init__`. Follow the pattern
   in `apps/trello/references/web/base_api_service.py` (query-param auth) or
   `apps/jira/references/web/base_api_service.py` (Bearer token auth).

4. Write API service classes under `references/web/api/` — one file per resource group
   (e.g. `pages.py`, `databases.py`). Use `@deserialized` for return types.

5. Write DTOs under `references/dto/` as `@dataclass` classes with all `Optional` fields.

6. Write `mcp.py` with a `register_<name>_tools(mcp: FastMCP)` function that exposes
   all key operations as MCP tools. Follow the pattern in `apps/trello/mcp.py`:
   - One `@mcp.tool()` per operation
   - Descriptive docstring with Args section
   - `logger.info(...)` at entry and on result
   - Defensive `isinstance` check before returning

7. Register the MCP tools in `mcp/server.py`:
   - Add `from apps.<name>.mcp import register_<name>_tools`
   - Add `register_<name>_tools(mcp)` with a `logger.info(...)` line before it

8. Write a `README.md` covering: description, auth setup, directory structure,
   available services table, MCP tools table, and how to run tests.

9. Write tests under `tests/` using `pytest` + `hamcrest`. Use `@pytest.mark.smoke`
   for fast read-only checks and `@pytest.mark.sanity` for broader coverage.
   All tests are live integration tests — no mocks.

10. Update the root `README.md`:
    - Add a row to the **App Inventory** table (name, integration description, type, tests, links)
    - Add the app directory entry to the **Directory Structure** `apps/` block
    - Add any new env vars to the **Environment Variables** block in the Configuration section

11. Remind the user to:
    - Add the app section to `apps_config.yaml`
    - Add any required env vars to `.env/apps.env`
    - Add the app to the App Inventory table in `CLAUDE.md`
