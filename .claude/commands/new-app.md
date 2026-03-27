Scaffold a new app integration under `apps/`.

The argument $ARGUMENTS is the new app name in snake_case (e.g. `stripe`, `notion`).

Steps:
1. Create the directory `apps/$ARGUMENTS/` with the standard structure:
   ```
   apps/<name>/
   ├── __init__.py
   ├── config.py
   ├── references/
   │   ├── __init__.py
   │   ├── dto/
   │   │   └── __init__.py
   │   └── web/
   │       └── api/
   │           └── __init__.py
   └── tests/
       └── __init__.py
   ```
2. Write `config.py` using the standard pattern:
   ```python
   from core.config.service import ConfigLoaderService
   from core.web.services.rest.config import AppConfigWSClient

   load_config = ConfigLoaderService().config
   APP_NAME = '<NAME_UPPER>'
   CONFIG = AppConfigWSClient(**load_config[APP_NAME])
   ```
3. Remind the user to:
   - Add the app section to `apps_config.yaml`
   - Add any required env vars to `.env/apps.env`
   - Add the app to the App Inventory table in `CLAUDE.md`
