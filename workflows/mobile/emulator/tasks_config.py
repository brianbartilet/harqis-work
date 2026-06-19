"""
Beat schedule for the mobile/emulator workflow.

INTENTIONALLY EMPTY — the emulator tasks are on-demand (started via the MCP
tools, the CLI at scripts/agents/emulator/run_emulator.py, or an explicit
.delay()/.apply_async() call), not on a timer. The tasks themselves are still
registered with Celery via `SPROUT.autodiscover_tasks(['workflows'])`, so they
can be invoked directly without any beat entry.

If you later want a periodic "keep profile X warm" job, add an entry here that
calls `workflows.mobile.emulator.tasks.ensure_emulator` (it's idempotent — it
only starts the AVD when it isn't already running) and union this dict into
workflows/config.py's CONFIG_DICTIONARY.

Manifesto metadata (for the registry/docs tooling, mirrors other workflows):

| Task             | code_role | para_bucket | express_target | review_artifact | hfl_signal |
| ---------------- | --------- | ----------- | -------------- | --------------- | ---------- |
| start_emulator   | execute   | resource    | process:avd    | es_log          | False      |
| ensure_emulator  | execute   | resource    | process:avd    | es_log          | False      |
| stop_emulator    | execute   | resource    | process:avd    | es_log          | False      |
| list_emulators   | observe   | resource    | return         | es_log          | False      |
| create_avd       | execute   | resource    | file:avd       | es_log          | False      |
"""

WORKFLOW_MOBILE_EMULATOR: dict = {}
