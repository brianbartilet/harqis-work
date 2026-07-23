---
name: run-tests
description: >
  Run tests for a specific app, pytest path, or the full harqis-work suite using the
  repository test conventions.
user-invocable: true
allowed-tools: Bash Read Glob Grep
---

Run tests for a specific app or the full suite.

The argument $ARGUMENTS is an optional app name (e.g. `echo_mtg`, `scryfall`, `ynab`) or a direct pytest path.

Rules:
- Invoke pytest through the repository interpreter: `.venv/bin/python -m pytest`. Do not rely on a globally resolved `pytest` executable.
- If $ARGUMENTS is empty, run `.venv/bin/python -m pytest` (excludes `workflows/` by default via pytest.ini).
- If $ARGUMENTS is an app name like `echo_mtg`, run `.venv/bin/python -m pytest apps/echo_mtg/tests/ -v`.
- If $ARGUMENTS is a file path, pass it directly to `.venv/bin/python -m pytest`.
- All tests are live integration tests — they require `.env/apps.env` and `apps_config.yaml` to be present and populated.
- Never mock external services. If credentials are missing, surface the error clearly.

Scheduled smoke tests:
- Run `PYTEST_TIMEOUT=30 bash scripts/agents/testing/smoke-tests.sh`; do not duplicate its pytest command in scheduler prompts.
- `pytest-timeout>=2.4,<3` is an explicit repository dependency compatible with pytest 8.x. Verify it with `.venv/bin/python -c 'import pytest_timeout'` after dependency upgrades or venv rebuilds.
- Keep per-test `--timeout` protection in signal mode for the macOS host.
- Read pass/fail/error/skip totals from `results/smoke-tests-junit.xml` through `scripts/agents/testing/smoke_summary.py`; do not parse verbose pytest output with chained `grep -c ... || echo 0`, which can create multi-line shell values.
- A run that exits before collection is an ERROR with zero executed tests, not an ordinary test failure.

After running, report:
- Pass / fail counts
- Any failures with the exception message and file:line
- Whether the failure looks like a credential issue vs a code issue
