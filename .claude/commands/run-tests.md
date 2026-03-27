Run tests for a specific app or the full suite.

The argument $ARGUMENTS is an optional app name (e.g. `echo_mtg`, `scryfall`, `ynab`) or a direct pytest path.

Rules:
- If $ARGUMENTS is empty, run `pytest` (excludes `workflows/` by default via pytest.ini).
- If $ARGUMENTS is an app name like `echo_mtg`, run `pytest apps/echo_mtg/tests/ -v`.
- If $ARGUMENTS is a file path, pass it directly to pytest.
- All tests are live integration tests — they require `.env/apps.env` and `apps_config.yaml` to be present and populated.
- Never mock external services. If credentials are missing, surface the error clearly.

After running, report:
- Pass / fail counts
- Any failures with the exception message and file:line
- Whether the failure looks like a credential issue vs a code issue
