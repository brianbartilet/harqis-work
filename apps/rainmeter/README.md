# Rainmeter

## Description

- [Rainmeter](https://www.rainmeter.net/) is a Windows desktop customization and monitoring tool that renders skins (INI-based widgets) on the desktop.
- This app provides Python helpers to generate skins from templates, push data to the HUD feed, and manage Rainmeter settings programmatically.
- Used by all `hud` workflow tasks to display live data (forex, calendar, budgets, orders) as desktop widgets.

## Supported Automations

- [ ] webservices
- [ ] browser
- [X] desktop
- [ ] mobile
- [ ] internet of things

## Directory Structure

```
apps/rainmeter/
├── config.py
├── references/
│   └── helpers/
│       ├── bangs.py            # Rainmeter CLI command wrappers
│       ├── config_builder.py   # @init_meter decorator + skin rendering
│       ├── settings.py         # Read/write Rainmeter.ini settings
│       └── smart_profiles.py   # Schedule-aware profile switching
└── tests/
```

## Helper Modules

### `bangs.py`
Wraps Rainmeter's `!Bang` CLI commands, executed via `Rainmeter.exe` without stealing window focus.

| Function | Description |
|----------|-------------|
| `_send_rainmeter_cmd_no_focus()` | Run a Rainmeter bang without focus steal |
| `_activate_config(skin)` | Activate a skin config |
| `_deactivate_config(skin)` | Deactivate a skin config |
| `_refresh_app()` | Refresh all Rainmeter skins |
| `_refresh_skin(skin)` | Refresh a single skin |

### `config_builder.py`
Provides the `@init_meter(meter_name, skin)` decorator used by all `hud` workflow tasks.

When applied to a task function it:
1. Prepares skin directories under `RAINMETER_WRITE_SKINS_TO_PATH`
2. Renders an INI skin file from a Jinja2/string template
3. Manages data/notes text files for the skin
4. Detects content changes and toggles a border color indicator
5. Plays a sound on update (optional)
6. Activates/refreshes the Rainmeter skin
7. Handles schedule-based activation (e.g. only show during work hours)

### `settings.py`
Reads and writes `Rainmeter.ini` (encoded in UTF-16 LE).

| Function | Description |
|----------|-------------|
| `set_rainmeter_always_on_top(value)` | Set `AlwaysOnTop` in Rainmeter.ini |

### `smart_profiles.py`
Schedule-aware profile switching based on the active foreground application.

| Function | Description |
|----------|-------------|
| `load_rainmeter_profile(app_exe)` | Load the iCUE/Rainmeter profile for the given app |
| `run_profile_scheduler()` | Read active window and switch to matching profile |

`PROFILE_SCHEDULE` maps layout categories to time-based activation rules.

## Configuration (`apps_config.yaml`)

```yaml
RAINMETER:
  app_id: 'rainmeter'
  app_data:
    bin_path: ${RAINMETER_BIN_PATH}
    static_path: ${RAINMETER_STATIC_PATH}
    write_skins_to_path: ${RAINMETER_WRITE_SKINS_TO_PATH}
    write_feed_to_path: ${RAINMETER_WRITE_FEED_TO_PATH}
```

`.env/apps.env`:

```env
RAINMETER_BIN_PATH=C:\Program Files\Rainmeter\Rainmeter.exe
RAINMETER_STATIC_PATH=C:\path\to\static\skin\assets
RAINMETER_WRITE_SKINS_TO_PATH=C:\Users\<user>\Documents\Rainmeter\Skins\HARQIS
RAINMETER_WRITE_FEED_TO_PATH=C:\path\to\feed\data
```

## How to Use

The `@init_meter` decorator is applied directly in workflow task definitions:

```python
from core.apps.sprout.app.celery import SPROUT
from core.apps.sprout.decorators import log_result, feed
from apps.rainmeter.references.helpers.config_builder import init_meter

@SPROUT.task(queue='hud')
@log_result()
@init_meter(meter_name='FOREX', skin='HARQIS_DESKTOP')
@feed()
def show_forex_account(**kwargs):
    # return data that gets rendered into the skin
    return {'balance': '...', 'pl': '...'}
```

## Notes

- Rainmeter must be installed and running for skins to activate.
- Skin files are UTF-8 INI format; Rainmeter.ini uses UTF-16 LE.
- `bangs.py` uses `subprocess` with `STARTF_USESHOWWINDOW` to prevent CLI windows from appearing on screen.
- The `hud` workflow's `show_hud_profiles` task calls `run_profile_scheduler()` at midnight to initialize the correct profile.
