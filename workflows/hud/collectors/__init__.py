"""
workflows/hud/collectors/

Win32-free data collectors extracted from the HUD render tasks. Each
``collect_<slug>(**kwargs) -> dict`` returns the SAME ``{"text", "summary",
"metrics", ...}`` payload its HUD task returns — the pure capture/distill stage,
with no Rainmeter/win32 dependency.

Both sides import these:
  * ``workflows/hud/tasks/hud_<slug>.py`` — the Windows render task calls the
    collector, then renders the result into a Rainmeter skin.
  * ``workflows/hud/tasks/hud_data_only.py`` — the always-on host twin calls the
    same collector and only writes the @feed dump + @log_result ES record.

Single source of truth → no drift between what Windows renders and what the
host logs. Generated/maintained by the `/create-data-only-from-hud` skill.
"""
