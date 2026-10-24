import sys

# API/file-snapshot collectors use portable text output on every platform.
import workflows.hud.tasks.hud_forex
import workflows.hud.tasks.hud_calendar
import workflows.hud.tasks.hud_logs
import workflows.hud.tasks.hud_finance
import workflows.hud.tasks.hud_jira
import workflows.hud.tasks.hud_api_costs
import workflows.hud.tasks.hud_radar

# Desktop inspection and existing TCG fulfillment side effects retain Windows affinity.
if sys.platform == "win32":
    import workflows.hud.tasks.hud_tcg
    import workflows.hud.tasks.hud_gpt
    import workflows.hud.tasks.hud_utils
    import workflows.hud.tasks.second_brain

# Retain the fallback task for compatibility; it is no longer scheduled.
import workflows.hud.tasks.hud_data_only
import workflows.hud.tasks.hermes_radar_export
