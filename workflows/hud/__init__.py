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
    import workflows.hud.tasks.hud_jira
    import workflows.hud.tasks.hud_api_costs
    import workflows.hud.tasks.hud_radar

# Host-safe HUD support tasks run on the always-on host (non-Windows included).
# These modules contain collectors/feed/export logic only — no Rainmeter calls.
import workflows.hud.tasks.hud_data_only  # noqa: E402,F401
import workflows.hud.tasks.hermes_radar_export  # noqa: E402,F401
