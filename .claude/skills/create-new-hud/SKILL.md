Scaffold a new Rainmeter HUD widget under `workflows/hud/tasks/hud_<name>.py` from a description, copying the layout/dimension pattern of an existing widget. Wires up the section dict, the schedule entry in `tasks_config.py`, the import in `workflows/hud/__init__.py`, the docs row in `workflows/hud/README.md`, and the panel row in the root `README.md` Desktop HUD section. Optionally adds a new `WorkflowQueue` value when the user wants the task on a dedicated queue.

## Arguments

`$ARGUMENTS` format (parse left to right):

```
[<hud_title>] [<task_description_or_screenshot_path>] [--reference <existing_hud>] [--no-prompt]
```

| Token | Required | Description |
|---|---|---|
| `hud_title` | Yes | Display name shown in the HUD title bar (e.g. `"JIRA BOARD"`, `"YNAB SUMMARY"`). The task file is named `hud_<slug>.py` where `slug = hud_title.lower().replace(" ", "_")`. |
| `task_description_or_screenshot_path` | Yes | Free-text description of what the widget should show, OR a path to a screenshot/text file showing the layout. |
| `--reference <existing_hud>` | No | Existing widget to copy dimensions from (e.g. `show_tcg_orders`, `hud_calendar`). Default: `show_tcg_orders`. |
| `--no-prompt` | No | Skip the Step-0 question pass and assume sane defaults (Q&A is recommended). |

---

## Step 0 — Ask before writing any code

Before scaffolding, collect answers to the following questions if they cannot be confidently inferred from `$ARGUMENTS`. Ask them ONE BY ONE so the user can correct partial answers without re-typing the rest.

### Q1. HUD title
Display title used in the Rainmeter header AND used to derive the task name + skin folder. Examples: `"JIRA BOARD"`, `"YNAB SUMMARY"`, `"OANDA POSITIONS"`. From this:
- Task file: `workflows/hud/tasks/hud_<slug>.py`  (slug = lowercased + underscored)
- Task function: `show_<slug>`  (or another verb the user prefers)
- HUD item name passed to `@init_meter`: the title verbatim (uppercase enforced by the template).

### Q2. Header links
Top-row clickable URLs the user wants. The template's default `meterLink` slot is the leftmost link; additional `meterLink_<name>` slots sit to its right and render with a `|<LABEL>` prefix so the visible bar reads `LABEL1|LABEL2|LABEL3` like the existing widgets. For each link, capture:
- Label text (e.g. `JIRA_BOARD`, `DUMP`, `DASHBOARD`)
- URL or local path
- Whether the URL value should come from a task **kwarg** so it can be reconfigured per-environment without editing code. URLs that point at user-specific dashboards / boards / repos almost always belong as required kwargs — passing them via the schedule entry (`kwargs={"dashboard_url": "..."}`) means the URL change is one config edit, not a code edit.

**Don't hand-tune `X=` or `W=`.** Use the layout helper — it returns one `(X, W)` pair per label so the click region matches the rendered text width and adjacent meters don't overlap:

```python
from workflows.hud.helpers.layout import compute_horizontal_link_layout

# User-supplied links FIRST, DUMP appended last (default placeholder so the
# generated text file is always one click away while building/debugging the HUD).
header_labels = ["BOARD", "DASHBOARD", "REPOSITORY", "STRUCTURE", "DUMP"]
layout = compute_horizontal_link_layout(header_labels)
# layout is [(10, 34), (50, 64), …] — list of (X, W) per label.

x0, w0 = layout[0]
ini['meterLink']['X'] = '({0}*#Scale#)'.format(x0)
ini['meterLink']['W'] = str(w0)
# ... and so on for each meterLink_<slot>; see Step 4 skeleton.
```

The helper reads `len(label) * px_per_char` for both X and W, accounts for the leading `|` separator on labels 1+, and adds a small gap between meters. Renaming "DASHBOARD" → "DASH" or adding a 6th link updates the layout automatically.

**DUMP placeholder convention:** the DUMP link (opens the widget's own dump.txt for inspection) is appended *after* the user's links so the user-facing labels read left-to-right by domain importance and DUMP — a developer convenience — sits on the right edge. Skip the DUMP slot only when the user explicitly says so.

### Q3. Sample text output
Ask for the verbatim text the dump should produce, including:
- Header line(s) — e.g. `========\n<TITLE>\n========`
- Column headers — typically aligned to a 88-char row
- A few sample rows so the column widths can be inferred
- The `[SCROLL FOR MORE] ... [END]` wrapper is added automatically; do not include it in the sample.

If the user provides a screenshot path, use the Read tool on it and infer the table layout from the image.

### Q4. Dimensions
Three width options:
- **(default)** Copy from `--reference` (default `show_tcg_orders`): `width_multiplier=3`, 88-char rows, `42`-px header padding, `22`-px line height. This works for most table-style HUDs.
- **Copy from another widget** — accept e.g. `--reference hud_calendar` to mirror that widget's narrower layout.
- **User-supplied** — ask for `width_multiplier` and confirm the row width in characters.

**Height: prefer dynamic auto-cropping** — instead of a fixed `max_hud_lines = N` constant, compute `max_hud_lines` from the actual dump length so the HUD shrinks to fit content + a small buffer (no big empty area below the last row, like the previous JIRA BOARD widget). Cap with a maximum so a long dump doesn't expand the widget across the screen — beyond the cap, `MeasureScrollableText` handles overflow.

Use the shared helper rather than re-implementing per widget:

```python
from workflows.hud.helpers.sizing import (
    DEFAULT_MAX_HUD_LINES,                # 14 — tune via the `cap` argument
    compute_max_hud_lines,
)

# In the task body, AFTER the dump is composed:
max_hud_lines = compute_max_hud_lines(dump)             # default cap (14)
# or, for a tighter widget that scrolls sooner:
max_hud_lines = compute_max_hud_lines(dump, cap=8)

ini['Variables']['ItemLines'] = str(max_hud_lines)
```

Expose `max_hud_lines` as a kwarg on the task function so each invocation can override the cap (a Beat schedule entry can pass `"max_hud_lines": 10` for a tighter view, an ad-hoc call can pass `20` for a taller one).

**The order matters**: build the dump FIRST, then size dimensions from `compute_max_hud_lines(dump)`. The previous version of the JIRA BOARD widget set dimensions before composing the dump and ended up with a screen-tall HUD with empty space — don't reproduce that.

Reminder of the dimension formulas (mirror these unless the user overrides):
```python
width_multiplier = 3
ini['MeterDisplay']['H']        = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'
ini['Rainmeter']['SkinHeight']  = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'   # +6 px over background = border render room
ini['Rainmeter']['SkinWidth']   = '({0}*198*#Scale#)'.format(width_multiplier)  # +8 px over background
ini['MeterBackground']['Shape'] = 'Rectangle 0,0,({0}*190),(36+(#ItemLines#*22)),2 ...'
```

Sticking to a fixed `max_hud_lines` is acceptable when the widget always renders a known number of rows (e.g. exactly N accounts, exactly M time slots). For variable-row HUDs (Jira boards, ticket queues, search results), use the dynamic recipe above.

### Q4b. Display mode (scrollable / static / marquee)

How should the rendered text behave when the dump exceeds the visible HUD height? Pick one:

| Mode | Measure binding | When to use | Examples |
|---|---|---|---|
| **Scrollable (manual)** | `MeasureScrollableText` (Lua: `ScrollableText.lua`) | The user expects to read the rows and scroll through them with the mouse wheel. Default for table/list-style widgets. | `show_tcg_orders`, `show_tcg_sell_cart`, `show_jira_board`, `get_failed_jobs` |
| **Marquee / ticker** | `MeasureLuaScriptScroll` (Lua: `TextCycle.lua`) | The dump is a stream of fast-moving content the user only glances at — auto-cycles every `ScrollDelay` frames. | `get_desktop_logs`, `get_events_world_check` |
| **Static** | (none — leave the template default `MeasureLuaScript`) | The dump is short and fits in the visible window. No interaction expected. | `show_calendar_information`, `show_mouse_bindings` |

Code patterns to write into the dimensions region of the task:

```python
# Scrollable (mouse-wheel)
ini['MeterDisplay']['MeasureName'] = 'MeasureScrollableText'
ini['Variables']['ItemLines'] = '{0}'.format(max_hud_lines)

# Marquee / ticker (auto-scroll)
ini['MeterDisplay']['MeasureName'] = 'MeasureLuaScriptScroll'
# Optional: tune ScrollDelay (frames between scrolls) — see base.ini.
ini['Variables']['ItemLines'] = '{0}'.format(max_hud_lines)

# Static — no Python override; the base template's `MeasureLuaScript`
# already reads dump.txt straight through. Skip the `MeasureName` line.
ini['Variables']['ItemLines'] = '{0}'.format(max_hud_lines)
```

If the user is unsure, default to **Scrollable** — it's the most useful for any widget with more than a handful of rows, and the mouse wheel is non-destructive (the user can ignore it).

---

### Q5. Calendar schedule (`schedule_categories`)
Which calendar block(s) should the HUD be visible during? Pick from `apps/google_apps/references/constants.ScheduleCategory`:
- `WORK`        — `"Career | Work"` — work-hour HUDs (Jira, queues, build dashboards).
- `PLAY`        — `"Mischief | Misdirection | Play"` — game/MTG/casual widgets.
- `FINANCE`     — `"Finance | Investing | Business"` — budget/forex/positions.
- `ORGANIZE`    — `"Organization | Everyman Skills"` — todo/calendar/notes.
- `PINNED`      — always visible.
- `DEACTIVATED` — never auto-shows; manual trigger only.

Ask which is the best fit. If unsure, default to `PINNED`.

### Q6. Celery schedule + queue
Two parts:
- **Schedule** — crontab pattern. Common defaults:
  - `crontab(minute=0)` — every hour on the hour
  - `crontab(day_of_week='mon-fri', minute=0)` — weekdays every hour
  - `crontab(minute='*/15')` — every 15 minutes
  - `timedelta(seconds=30)` — sub-minute polling
- **Queue** — pick from `WorkflowQueue` (`HUD`, `TCG`, `DEFAULT`, `ADHOC`, `PEON`) or invent a new one. If new, the skill MUST also extend `WorkflowQueue` and register the queue in `workflows/config.py` (Step 5).

Ask the user. Default queue: `HUD`. Default schedule: `crontab(minute=0)`.

### Q7. Apps required
List every `apps/<name>` integration the widget needs to fetch data from (e.g. `apps/jira`, `apps/oanda`, `apps/ynab`). For each:
- Confirm the app exists under `apps/`. If missing, suggest `/create-new-service-app <name>` to scaffold it before continuing.
- Identify the specific service class + method to call. If the existing service doesn't expose what the HUD needs, build the new endpoint inside the same app (separate file is fine — see `apps/jira/references/web/api/boards.py` for the pattern).

### Q8. Confirmation
Print a one-block summary of the answers and ask for sign-off before writing files:

```
HUD scaffold plan:
  Title:                  JIRA BOARD
  Task file:              workflows/hud/tasks/hud_jira.py
  Task function:          show_jira_board
  Reference dimensions:   show_tcg_orders (3x width, 88-char rows)
  Header links:           JIRA_BOARD (kwarg-configured URL), DUMP
  Display mode:           Scrollable (mouse-wheel — MeasureScrollableText)
  Schedule category:      WORK (visible during Career | Work calendar block)
  Celery schedule:        crontab(day_of_week='mon-fri', minute=0)  → weekdays hourly
  Queue:                  peon (NEW — added to WorkflowQueue + config.py)
  Apps used:              apps/jira (new endpoint: ApiServiceJiraBoards)
  Sample columns:         T(6)  Summary(40)  Assignee(22)  FixV(6)  Priority(8)  = 88 chars

Proceed? (y/n)
```

---

## Step 1 — Add a new queue to `workflows/queues.py` (only if the user picked a new queue)

If the user named a queue that doesn't already exist in `WorkflowQueue`:

1. Add the new member alphabetically among the direct queues:
   ```python
   class WorkflowQueue(StrEnum):
       DEFAULT = "default"
       HUD = "hud"
       TCG = "tcg"
       ADHOC = "adhoc"
       PEON = "peon"   # one-line comment describing the use case
       ...
   ```
2. Register the queue in `workflows/config.py`:
   ```python
   SPROUT.conf.task_queues = (
       Queue(WorkflowQueue.DEFAULT.value),
       ...
       Queue(WorkflowQueue.PEON.value),         # NEW
       Broadcast(WorkflowQueue.HUD_BROADCAST.value),
   )
   ```
3. Skip if the user picked an existing queue.

---

## Step 2 — Build any missing app endpoints

For each app/service the widget needs:

- If the service method already exists, skip.
- If not, build it inside the same app (`apps/<name>/references/web/api/<resource>.py`). Mirror the patterns of nearby services — see `apps/jira/references/web/api/boards.py` for an example that adds a new endpoint with a different base URL than the existing services in the same app.
- Add the corresponding DTO under `apps/<name>/references/dto/` if the response shape isn't trivial enough to keep as a raw dict.
- Add a unit test under `apps/<name>/tests/` if the new endpoint has parsing logic worth covering.

---

## Step 3 — Add a section dict to `workflows/hud/tasks/sections.py`

Append a new dict named `sections__<slug>` after the existing entries:

```python
sections__<slug> = {
    # `meterLink` (template default) is used for "<HUD TITLE>" in show_<slug>.
    # `meterLink_dump` is the second top-row slot — opens dump.txt.
    "meterLink_dump": {
        "Preset": "InjectedByTest",
    },
    # ...add one entry per additional meterLink_<x> slot the task uses.
}
```

**Important:** include only meter slots the task actually fills. Empty/unused entries render as placeholder strings ("Link 2", "Link 3") on the HUD.

---

## Step 4 — Write `workflows/hud/tasks/hud_<slug>.py`

Mirror the structure of the chosen reference widget. The skeleton:

```python
"""
<HUD TITLE> HUD widget.

<one-paragraph description of what this widget does>
"""

import os
from typing import List, Optional

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import logger as log
from core.utilities.data.strings import make_separator
from core.utilities.resources.decorators import get_decorator_attrs

from apps.rainmeter.references.helpers.config_builder import ConfigHelperRainmeter, init_meter
from apps.desktop.helpers.feed import feed

from apps.<app_a>.references.web.api.<resource> import ApiService<AppA><Resource>
from apps.google_apps.references.constants import ScheduleCategory

from apps.rainmeter.config import CONFIG as RAINMETER_CONFIG
from apps.<app_a>.config import APP_NAME as APP_NAME_<APP_A>
from apps.apps_config import CONFIG_MANAGER

from workflows.hud.helpers.sizing import (
    DEFAULT_MAX_HUD_LINES,
    compute_max_hud_lines,
)
from workflows.hud.helpers.text import truncate
from workflows.hud.tasks.sections import sections__<slug>


@SPROUT.task()
@log_result()
@init_meter(RAINMETER_CONFIG, hud_item_name='<HUD TITLE>',
            new_sections_dict=sections__<slug>,
            play_sound=False,
            schedule_categories=[ScheduleCategory.<CATEGORY>, ])
@feed()
def show_<slug>(ini=ConfigHelperRainmeter(),
                <kwarg_a>: <type> = <default>,
                <kwarg_b>: <type> = <default>,
                max_hud_lines: int = DEFAULT_MAX_HUD_LINES,
                **kwargs):
    """<one-line summary>.

    Args:
        <kwarg_a>:    Description.
        <kwarg_b>:    Description.
        max_hud_lines: Visible HUD line cap. Default `DEFAULT_MAX_HUD_LINES` (14).
                       Beyond this the dump scrolls instead of growing.
        cfg_id__<a>:  Config key for <App A> (default '<APP_A>').
    """
    log.info("show_<slug> kwargs: %s", list(kwargs.keys()))

    # region Fetch
    cfg_id__<a> = kwargs.get('cfg_id__<a>', APP_NAME_<APP_A>)
    cfg__<a> = CONFIG_MANAGER.get(cfg_id__<a>)
    api_<a> = ApiService<AppA><Resource>(cfg__<a>)
    # ...fetch data...
    # endregion

    # region Build links — header (positioned dynamically by label width)
    meta = get_decorator_attrs(show_<slug>, prefix='')
    hud_item = str(meta['_hud_item_name']).replace(" ", "").upper()
    dump_path = os.path.join(
        RAINMETER_CONFIG['write_skin_to_path'],
        RAINMETER_CONFIG['skin_name'],
        hud_item,
        "dump.txt",
    )

    # User-supplied links FIRST, DUMP appended last as a placeholder for
    # quickly viewing the rendered dump.txt (debugging convenience).
    header_labels = ["<HEADER LABEL>", "<EXTRA1>", "<EXTRA2>", "DUMP"]
    layout = compute_horizontal_link_layout(header_labels)

    # 0 — leftmost label uses the template's default `meterLink` slot.
    x0, w0 = layout[0]
    ini['meterLink']['text'] = header_labels[0]
    ini['meterLink']['leftmouseupaction'] = '!Execute ["{0}" 3]'.format(<header_url>)
    ini['meterLink']['tooltiptext'] = <header_url>
    ini['meterLink']['X'] = '({0}*#Scale#)'.format(x0)
    ini['meterLink']['W'] = str(w0)

    # 1+ — additional `meterLink_*` slots; each gets a `|<LABEL>` prefix.
    # `exec_arg='3'` opens URLs in the system default browser; the local
    # `dump_path` is a file path so it skips the arg.
    extra_links = [
        ("meterLink_<a>",    header_labels[1], <extra1_url>, "3"),
        ("meterLink_<b>",    header_labels[2], <extra2_url>, "3"),
        ("meterLink_dump",   header_labels[3], dump_path,    None),
    ]
    for i, (slot, label, target, exec_arg) in enumerate(extra_links, start=1):
        x, w = layout[i]
        ini[slot]['Meter'] = 'String'
        ini[slot]['MeterStyle'] = 'sItemLink'
        ini[slot]['X'] = '({0}*#Scale#)'.format(x)
        ini[slot]['Y'] = '(38*#Scale#)'
        ini[slot]['W'] = str(w)
        ini[slot]['H'] = '55'
        ini[slot]['Text'] = '|{0}'.format(label)
        action = '!Execute ["{0}" {1}]'.format(target, exec_arg) if exec_arg \
            else '!Execute ["{0}"]'.format(target)
        ini[slot]['LeftMouseUpAction'] = action
        ini[slot]['tooltiptext'] = target
    # endregion

    # region Compose dump (88-char-wide rows) — must come BEFORE dimensions
    # so `compute_max_hud_lines(dump)` can crop the HUD to actual content.
    dump = ""
    # ...build the table from the fetched data...

    dump = "[SCROLL FOR MORE]\n" + dump + "\n[END]"
    # endregion

    # region Set dimensions — height auto-cropped to dump line count + buffer
    width_multiplier = 3
    max_hud_lines = compute_max_hud_lines(dump, cap=max_hud_lines)

    ini['meterSeperator']['W'] = '({0}*186*#Scale#)'.format(width_multiplier)
    ini['MeterDisplay']['W'] = '({0}*190*#Scale#)'.format(width_multiplier)
    ini['MeterDisplay']['H'] = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'

    ini['Rainmeter']['SkinWidth'] = '({0}*198*#Scale#)'.format(width_multiplier)
    ini['Rainmeter']['SkinHeight'] = '((42*#Scale#)+(#ItemLines#*22)*#Scale#)'

    ini['MeterBackground']['Shape'] = ('Rectangle 0,0,({0}*190),(36+(#ItemLines#*22)),2 | Fill Color #fillColor# '
                                       '| StrokeWidth (1*#Scale#) | Stroke Color [#darkColor] '
                                       '| Scale #Scale#,#Scale#,0,0').format(width_multiplier)
    ini['MeterBackgroundTop']['Shape'] = ('Rectangle 3,3,({0}*187),25,2 | Fill Color #headerColor# | StrokeWidth 0 '
                                          '| Stroke Color [#darkColor] | Scale #Scale#,#Scale#,0,0').format(width_multiplier)

    ini['meterTitle']['W'] = '({0}*190*#Scale#)'.format(width_multiplier)
    ini['meterTitle']['X'] = '({0}*190*#Scale#)/2'.format(width_multiplier)

    # Display mode (chosen in Q4b):
    #   Scrollable (manual mouse-wheel) → 'MeasureScrollableText'
    #   Marquee / ticker (auto-cycle)   → 'MeasureLuaScriptScroll'
    #   Static (no scrolling)           → omit this line entirely
    ini['MeterDisplay']['MeasureName'] = 'MeasureScrollableText'
    ini['Variables']['ItemLines'] = '{0}'.format(max_hud_lines)
    # endregion

    return dump


# Imports (top of the module):
#   from workflows.hud.helpers.sizing import (
#       DEFAULT_MAX_HUD_LINES,                # 14 — pass to `cap` to override
#       compute_max_hud_lines,
#   )
#   from workflows.hud.helpers.text import truncate
#
# Both helpers live in `workflows/hud/helpers/` so every widget shares one
# implementation. Do NOT re-define them inline per widget.
```

**Critical layout invariants** (reproduce verbatim — these are the difference between a clean HUD and a clipped one):

- `SkinHeight` formula must add `42` to the `#ItemLines#*22` multiplier. **NOT 36** — 36 matches the background rectangle exactly and clips the bottom border.
- `SkinWidth` formula uses `198` (the background rectangle is `190`). The 8-px slack carries the side strokes.
- Every row format string must total ≤88 chars or it wraps onto the next visual line.
- ConfigParser tooltip / text values containing `%` must escape the `%` as `%%` (e.g. `"Threshold: 10%%"`).

---

## Step 5 — Add the schedule entry to `workflows/hud/tasks_config.py`

Append a new entry inside `WORKFLOWS_HUD`:

```python
'run-job--show_<slug>': {
    'task': 'workflows.hud.tasks.hud_<slug>.show_<slug>',
    'schedule': crontab(<schedule from Step 0>),
    'kwargs': {
        "cfg_id__<a>": "<APP_A>",
        # ...repeat the kwargs the task accepts so the schedule is self-documenting...
    },
    "options": {
        "queue": WorkflowQueue.<QUEUE>,
        "expires": 60 * <expiry_seconds>,
    },
},
```

Pick `expires` such that a missed run can still fire within the natural cadence:
- Hourly schedule → `expires = 60 * 30` (half-cadence).
- Daily / weekly → `expires = 60 * 60 * 24` (one day).
- Sub-minute → `expires = 60 * 1`.

---

## Step 6 — Register the module in `workflows/hud/__init__.py`

Append the import inside the `if sys.platform == "win32":` guard so non-Windows hosts don't crash on Rainmeter imports:

```python
if sys.platform == "win32":
    import workflows.hud.tasks.hud_forex
    ...
    import workflows.hud.tasks.hud_<slug>   # NEW
```

Verify Celery sees the task:

```bash
.venv/bin/python -c "
from core.apps.sprout.app.celery import SPROUT
import workflows.hud
print('workflows.hud.tasks.hud_<slug>.show_<slug>' in SPROUT.tasks)
"
```

Should print `True`.

---

## Step 7 — Update `workflows/hud/README.md`

Append a row to the Scheduled Tasks table:

```markdown
| `show_<slug>` | <Schedule description> | <One-line description of what it shows>. Queue: `<queue>`. |
```

And a row to the Task Files table:

```markdown
| `tasks/hud_<slug>.py` | `show_<slug>` |
```

---

## Step 7b — Update the root `README.md` Desktop HUD section

Open `README.md`, find the `## Desktop HUD` section. There are two things that may need updating:

### 1. The panel inventory table (always)

Append (or merge) a row:

```markdown
| **<HUD TITLE>** | <Visibility> | <App / data source> — <one-line what it shows> | <Schedule description> |
```

- **Panel name** = the `hud_item_name` passed to `@init_meter`, in display case (`PC DAILY SALES`, `OANDA ACCOUNT`, `JIRA BOARD`).
- **Visibility** = `Always` (PINNED), `Finance block` (FINANCE), `Work block` (WORK), `Play block` (PLAY), `Organize block` (ORGANIZE), `Organize + Work` (combined), or `Manual only` (DEACTIVATED). Match what was passed to `schedule_categories=[ScheduleCategory.<X>]` in Step 4.
- **Data source** = the source app(s) + a tight description (e.g. `AppSheet INVOICE table — 60-day gross sales by month`).
- **Schedule** = the human-readable cadence (mirror Step 7's wording — `Every hour`, `Every 15 min (Mon–Fri)`, `Daily at midnight`, …).

Place the row in its visibility group (Always-visible widgets up top, then Finance, Work, Organize, Play). Skip this step ONLY for background-capture tasks with no `@init_meter` (e.g. `take_screenshots_for_gpt_capture`, `build_summary_mouse_bindings`).

### 2. The calendar-driven visibility table (only if the widget uses a category not already listed)

The `## Desktop HUD → Calendar-driven visibility` section maps each `ScheduleCategory` to the widgets that surface for it. If the new widget uses a category that **already has rows in that table**, append the panel name to the existing row's "Widgets that surface" cell — don't add a new row. If the widget uses a brand-new category (rare; usually the existing six cover everything), add a new row in the visibility-table.

If the panel inventory has drifted (panels exist in `tasks_config.py` but not in the README), add the missing rows in the same edit so the inventory stays complete.

---

## Step 8 — Write tests (mandatory)

Create `workflows/hud/tests/test_hud_<slug>.py`. Mirror the structure used by `workflows/hud/tests/test_hud_jira.py` and `test_hud_tcg.py` — **integration tests at the top, unit tests below**, no test classes, function names use the `test__<function_name>` double-underscore convention.

### 8a — Integration tests (live API)

Call the real task with the production config keys. These hit live endpoints and require working creds in `.env/apps.env`. No mocks.

```python
def test__show_<slug>():
    """Live call against the configured backend."""
    show_<slug>(
        cfg_id__<a>="<APP_A>",
        # mirror the kwargs from the schedule entry so the test exercises
        # the same code path Beat will use in production
    )


def test__show_<slug>_custom_input():
    """Variant — pass a different filter / id to confirm parameterisation."""
    show_<slug>(
        cfg_id__<a>="<APP_A>",
        <kwarg>=<alt_value>,
    )
```

If the task has irreversible side-effects (cart mutation, posting, sending), guard the destructive variant with `@pytest.mark.skip(reason="...")`.

### 8b — Unit tests for the render helpers (offline, no API)

Every helper extracted from the task body — row formatting, truncation, grouping, sorting, separator generation — gets a unit test. Use `pytest.mark.parametrize` for value-table inputs.

```python
@pytest.mark.parametrize("text,width,expected", [
    ("hello", 10, "hello"),                  # fits
    ("hello world!", 11, "hello wo..."),    # overflow → trimmed + ellipsis
    ("ab", 2, "ab"),                         # exact fit
    ("abcd", 3, "abc"),                      # width <= 3 → no ellipsis room
    (None, 5, ""),                           # None → empty
    (12345, 4, "1..."),                      # non-string coerced
])
def test__truncate(text, width, expected):
    assert _truncate(text, width) == expected


def test__render_<thing>_row_full_data():
    row = _render_<thing>_row(_SAMPLE_ITEM)
    assert row.endswith("\n")
    assert len(row.rstrip("\n")) == 88           # row width matches separator
    assert "<expected substring>" in row


def test__render_<thing>_row_handles_missing_fields_gracefully():
    """Sparse upstream response shouldn't crash the renderer."""
    row = _render_<thing>_row({"fields": {}})
    assert len(row.rstrip("\n")) == 88
```

### 8c — Section / table tests

If the task renders multiple sections (one per status, queue, account, etc.), assert:
- The section header is exactly the separator width (`"=" * 88`).
- The column header is present and uses the same widths as the data rows.
- The table-divider is `"-" * 88`.
- An empty section renders a friendly placeholder ("(no issues)", "No matching bids.", etc.).
- A section with an `error` payload surfaces the error string in the dump.

```python
def test__render_section_header_is_88_wide():
    out = _render_section({"status": "In Progress", "issues": []})
    lines = out.splitlines()
    assert lines[0] == "=" * 88
    assert lines[1] == "IN PROGRESS"
    assert lines[2] == "=" * 88


def test__render_section_no_issues_message():
    out = _render_section({"status": "Ready", "issues": []})
    assert "(no issues)" in out


def test__render_section_renders_issues_in_order():
    """Rendering must preserve the input order (no implicit sorting)."""
    section = {"status": "In Review", "issues": [<first>, <second>]}
    out = _render_section(section)
    assert 0 < out.find("first marker") < out.find("second marker")


def test__render_section_surfaces_fetch_error():
    out = _render_section({"status": "...", "issues": [], "error": "401 Unauthorized"})
    assert "401 Unauthorized" in out
```

### 8d — Run the suite

Before declaring the widget done, run only the unit tests (live tests need the real API and are slower):

```bash
.venv/bin/python -m pytest workflows/hud/tests/test_hud_<slug>.py \
    -k "not test__show_<slug>" -v --no-header
```

Then run the integration test once to verify live wiring:

```bash
.venv/bin/python -m pytest workflows/hud/tests/test_hud_<slug>.py::test__show_<slug> -v
```

### 8e — Test rules (enforced)

- **No test classes.** Module-level functions only.
- **No `@pytest.mark.smoke` / `@pytest.mark.integration` markers** — not used in this repo.
- **Use `@pytest.mark.skip(reason="...")` for tests that mutate live data.** The reason must describe the side effect.
- **Workflow tests pass real config-key strings** (`'JIRA'`, `'YNAB'`, etc.) — never mock `CONFIG_MANAGER`.
- **Unit tests may stub external services** but should prefer testing pure logic functions directly.

---

## Step 9 — Verify the dimensions render correctly

Before declaring done, eyeball the produced .ini:

```bash
ls "<RAINMETER_WRITE_SKINS_TO_PATH>/HARQIS_DESKTOP/<HUD_ITEM_NAME_NOSPACES>/"
grep -E "MeasureName|measurename|skinheight|measurescrollabletext" \
    "<RAINMETER_WRITE_SKINS_TO_PATH>/HARQIS_DESKTOP/<HUD_ITEM_NAME_NOSPACES>/<HUD_ITEM_NAME_NOSPACES>.ini"
```

Expected:
- `measurename = MeasureScrollableText` on `[MeterDisplay]`
- `skinheight = ((42*#Scale#)+(#ItemLines#*22)*#Scale#)`
- A `[MeasureScrollableText]` section is present

If the user reports the border is missing, the bottom row wraps, or scrolling doesn't trigger — re-check the `42` (not 36), 88-char row width, and `MeasureName` override respectively.

---

## Step 10 — Print the activation checklist

Print this at the end, filled in with the actual values:

```
HUD widget created. Manual steps to activate:

  Queue (Step 1 — only if a new queue was added):
  [ ] WorkflowQueue.<NAME> = "<value>" present in workflows/queues.py
  [ ] Queue(WorkflowQueue.<NAME>.value) registered in workflows/config.py
  [ ] If running on a node, restart the worker with -Q <queue_name>

  Module + schedule (Step 5–6):
  [ ] workflows/hud/__init__.py imports workflows.hud.tasks.hud_<slug>
  [ ] workflows/hud/tasks_config.py contains 'run-job--show_<slug>' entry
  [ ] Restart Celery Beat AND the worker

  Docs (Step 7 + 7b):
  [ ] workflows/hud/README.md has Scheduled Tasks + Task Files rows
  [ ] Root README.md Desktop HUD panel table has the new panel row

  Visual sanity (Step 9):
  [ ] Trigger one manual run: celery -A core.apps.sprout call workflows.hud.tasks.hud_<slug>.show_<slug>
  [ ] Reload the Rainmeter skin (right-click HUD → Refresh)
  [ ] Confirm the border, scrolling, and the JIRA_BOARD/DUMP links work

  Tests (Step 8 — must be written before declaring done):
  [ ] workflows/hud/tests/test_hud_<slug>.py exists
  [ ] Unit tests pass: pytest workflows/hud/tests/test_hud_<slug>.py -k "not test__show_<slug>" -v
  [ ] Integration test passes: pytest workflows/hud/tests/test_hud_<slug>.py::test__show_<slug> -v
```

---

## What NOT to do

- Don't override `MeterDisplay['H']` and `Rainmeter['SkinHeight']` with the **same** formula — the SkinHeight must be `((42*#Scale#)+(#ItemLines#*22)*#Scale#)` while the background uses `(36+(#ItemLines#*22))`. Equal heights clip the border stroke.
- Don't put unused meter slots in the `sections__<slug>` dict — Rainmeter renders them as placeholder strings ("Link 2", "Link 3").
- Don't forget the `if sys.platform == "win32":` guard in `workflows/hud/__init__.py`. HUD code imports `apps.rainmeter` and `apps.desktop`, which import `win32gui` etc. — non-Windows hosts will fail to start the worker if a HUD task is imported unconditionally.
- Don't include the `[SCROLL FOR MORE]` / `[END]` markers in the user's sample text when asking Q3 — the task wraps them automatically.
- Don't skip Step 1 if the user picked a queue not in the existing enum. The Celery worker silently drops messages routed to undeclared queues.
