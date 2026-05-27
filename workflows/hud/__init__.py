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

# Data-only fallback twins run on the always-on host (non-Windows included),
# so import unconditionally. The module is win32-free (collectors + feed +
# fallback gate + log_result — no Rainmeter), so this is safe on every OS.
import workflows.hud.tasks.hud_data_only  # noqa: E402,F401
