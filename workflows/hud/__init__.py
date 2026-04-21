import sys

# HUD tasks depend on Windows-only libraries (Rainmeter, win32gui).
# Skip silently on non-Windows platforms.
if sys.platform == "win32":
    import workflows.hud.tasks.hud_forex
    import workflows.hud.tasks.hud_tcg
    import workflows.hud.tasks.hud_gpt
    import workflows.hud.tasks.hud_calendar
    import workflows.hud.tasks.hud_logs
    import workflows.hud.tasks.hud_utils
    import workflows.hud.tasks.hud_finance
