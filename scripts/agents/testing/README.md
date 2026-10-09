# Daily app smoke tests

Run `SMOKE_TELEGRAM_NOTIFY=0 bash scripts/agents/testing/smoke-tests.sh` with the
repository virtual environment and app/machine configuration loaded. The runner
selects `pytest apps/ -m smoke`; unmarked and integration-only tests are deselected,
not counted as passes or skips. Omit `SMOKE_TELEGRAM_NOTIFY=0` only when the script
itself should deliver Telegram notifications.

## Quarantined live probes (2026-10-09)

These four user-reported recurring failures were confirmed in the latest daily
JUnit report. They are now marked **integration instead of smoke**, so daily
runs do not initialize their fixtures or contact these endpoints. Assertions and
fixture behavior remain unchanged: explicit/manual runs still expose failures.
This reduces daily coverage; it does not fix the services or credentials.

- `apps/pokemon_tcg/tests/test_cards.py::test_search_cards`: 30-second timeout.
  Restore after repeated successful bounded live runs.
- `apps/pokemon_tcg/tests/test_sets.py::test_list_sets`: timeout and unexpected
  retry payloads. Investigate the payload/adapter contract as well as availability;
  restore only after the original assertions pass reliably.
- `apps/google_apps/tests/test_tasks.py::test_list_task_lists`: OAuth
  `invalid_grant` during fixture setup. Reauthorize the configured Tasks account
  and verify the original test before restoring smoke coverage.
- `apps/youtube/tests/test_analytics.py::test_get_channel_summary`: Analytics API
  disabled/not configured (403). Enable/configure the API for the configured
  project and verify the original test before restoring smoke coverage.

Other tests, including Pokémon TCG's dex-number smoke probe, remain unchanged.
No broad application exclusion, catch-all exception handling, or permanent skip
is introduced. A pytest run without `-m smoke` can still execute these tests.

To diagnose only the quarantined probes after loading the normal repository
configuration (requires live credentials/network; no Telegram notification):

```bash
.venv/bin/python -m pytest -v --tb=short --timeout=30 --timeout-method=signal \
  apps/pokemon_tcg/tests/test_cards.py::test_search_cards \
  apps/pokemon_tcg/tests/test_sets.py::test_list_sets \
  apps/google_apps/tests/test_tasks.py::test_list_task_lists \
  apps/youtube/tests/test_analytics.py::test_get_channel_summary
```

To restore a probe, change its marker back to `smoke`, remove its quarantine
comment and entry above, and update `scripts/tests/test_smoke_quarantine.py`.
Do not restore merely to make the selection regression pass: first verify the
live prerequisite and original assertions.
