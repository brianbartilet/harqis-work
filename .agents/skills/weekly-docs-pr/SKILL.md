---
name: weekly-docs-pr
description: Run a scheduled or on-demand HARQIS documentation review and prepare a draft PR using the active LLM, with isolated Git work, source-backed edits, and explicit delivery handling.
---

# Weekly documentation PR

Use the current agent and configured model. No Claude Code executable or Claude
OAuth credentials are required. The caller or scheduler selects the runtime and
cadence; direct invocation does not wait for Sunday. Accept an optional target
(default `README.md`) and `--dry-run` (report only, no edits, PRs, or notifications).

## Review and publication

1. Resolve the repository and record its branch, commit, and working-tree state.
   Read applicable repository instructions. Use a separate worktree for the
   documentation branch; never switch or pull the running host's working branch.
2. Read [update-docs](../update-docs/SKILL.md) and use it as the source of truth for
   documentation review. Compare the requested target against implementation;
   make the smallest supported corrections and relevant cross-reference updates.
   Do not broaden the task into a code improvement scout.
3. Check existing open documentation PRs before duplicating a weekly change.
   When GitHub is unavailable, retain a local report and state that publication
   could not be checked or completed. Do not report an unrelated PR as success.
4. Validate paths, commands, and claims against source. Use the repository's
   virtual environment for any required Python checks. Record checks not run.
   If no drift exists, report that result; do not create an empty commit or PR.
5. When the caller requests a PR, stage only the reviewed documentation paths,
   use repository Conventional Commit conventions, push the worktree branch,
   and create a draft PR against the intended base (normally `main`). Use a body
   file for multiline CLI descriptions. Include the problem, corrections, and
   validation. Never merge or deploy as part of this skill.
6. Return the report, changed paths, validation results, actual runtime/model
   when known, and the verified PR URL or explicit publication failure.

## Python environment and notifications

The old server-local `~/.hermes/scripts/weekly_update_docs_pr.py` runs Claude and
imports the Telegram app inside its own Python process. Running it with Hermes's
Python can fail with `No module named 'core'`. This is a launcher/dependency issue,
not an LLM failure. Prefer executing this skill directly in the selected agent.

If a caller retains that compatibility script, launch it using the repository's
`.venv/bin/python` (macOS/Linux) or `.venv/Scripts/python.exe` (Windows), set the
working directory to that checkout, and load its standard machine environment
before app/workflow imports. Do not install repository packages into Hermes's
environment to work around the wrong interpreter.

For an import-only check from the repository root, use its venv with this code:

```python
import os
from scripts.deploy import load_env_into_os, load_machine_config, machine_env_vars
load_env_into_os()
os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")
os.environ.setdefault("WORKFLOW_CONFIG", "workflows.config")
os.environ.update(machine_env_vars(load_machine_config(None)))
import core
from apps.telegram.references.web.api.messages import ApiServiceTelegramMessages
print("Repository and Telegram imports available; no message sent.")
```

Return results through the caller's existing delivery mechanism. Send Telegram
messages only when explicitly authorized by the caller or job configuration; do
not duplicate an existing scheduler delivery. Report notification failures
separately from review/PR failures. Never print credentials. The legacy script's
`--dry-run` sends notifications and probes Claude; do not use it to implement
this skill's report-only dry run.
