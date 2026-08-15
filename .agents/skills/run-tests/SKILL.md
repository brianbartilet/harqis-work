---
name: run-tests
description: Run the repository's pytest regression or a selected app/path using the local virtual environment and repository configuration. Use for full, targeted, smoke, collection-only, or credential-backed test runs on Windows, macOS, or Linux.
---

# Run repository tests

Resolve the repository root, then choose its interpreter:

- Windows: `.venv/Scripts/python.exe`
- macOS/Linux: `.venv/bin/python`

Stop with a clear setup command if neither exists. Do not use a global `pytest` executable.

Before tests that import `apps.*` or `workflows.*`, load `.env/apps.env` and the current
machine's `machines.toml`/`machines.local.toml` environment using the repository environment
bootstrap available on this host. Never print resolved secret values.

Interpret `$ARGUMENTS` as follows:

- empty: `<python> -m pytest`
- app name: `<python> -m pytest apps/<app>/tests -v`
- existing path: `<python> -m pytest <path>`
- otherwise: pass supported pytest flags through unchanged

For smoke automation, use `scripts/agents/testing/smoke-tests.sh` when it exists. Treat an
exit before collection as an error with zero executed tests. Report passed, failed, errored,
skipped, and whether failures are code, environment, credential, network, or external-service
issues.

Tests marked manual/skip remain legitimate skips. Never run a destructive skipped test by
removing its marker.
