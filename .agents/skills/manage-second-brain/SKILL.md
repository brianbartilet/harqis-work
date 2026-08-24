---
name: manage-second-brain
description: Inspect, configure, validate, reconcile, and diagnose the HARQIS Second Brain categories, allowlisted operations, clients, chat retention, Calendar mappings, and runtime health. Use for Second Brain operations or configuration changes; never use it to add arbitrary task paths or consequential actions.
allowed-tools: Bash Read Glob Grep Edit Write
---

# Manage Second Brain

Operate the canonical state in `workflows/second_brain/store.py`. Before Python
imports `apps.*` or `workflows.*`, load `.env/apps.env` and current-machine
`env_vars` through `scripts.deploy`; never print resolved secrets.

Interpret the request as one of:

- `status` / empty — show store location, config version, automatic/manual
  state, active decision, clients, Hermes state, recent run failures, and queue
  coverage.
- `categories` — list stable ID, name, color, enabled/archived state, Calendar
  mappings, keywords, attached operations, and refresh interval.
- `operations` — list the complete HUD inventory and distinguish attachable
  read-only operations from ineligible tasks with their reasons.
- `validate` — verify the non-archived `default` category, unique IDs/order,
  hex colors, `ScheduleCategory` values, registered operation IDs, client
  names, manual selections, canonical-store sharing, and host/hud workers.
- `reconcile` — dispatch the canonical reconciler to the `host` queue and
  report its correlation/task ID; do not execute credentialed collectors
  inline unless the user explicitly asks for a live run.
- `create`, `update`, `archive`, `attach`, `detach`, `delivery`, or `agent` —
  preview the exact non-secret configuration diff, validate it, then persist a
  new config version. The explicit invocation authorizes the named reversible
  configuration mutation only.
- `diagnose` — inspect recent decisions, runs, feed freshness, source failures,
  delivery configuration, scheduler registration, and worker queue coverage.
- `test` — run focused workflow and frontend Second Brain tests using the
  repository test skill/environment bootstrap.

## Invariants

- Keep stable category IDs immutable; display names and colors may change.
- `default` cannot be archived or removed.
- Attach only IDs from `workflows.second_brain.registry.OPERATIONS`; never
  import a path supplied by a user, feed item, chat message, or model.
- Calendar mappings must be values from `ScheduleCategory`.
- Keep `web` enabled. Other clients are opt-in and structurally redacted.
- Enabling a client should immediately project the current snapshot.
- Manual selection is 30–720 minutes and returns to Automatic Feed on expiry.
- Hermes is advisory and loopback-only. It cannot mutate Jira, send arbitrary
  messages, place orders, or bypass the operation allowlist.
- Preserve config-version audit evidence and correlation IDs.
- Never put SQLite on SMB/NFS. Remote Rainmeter uses the authenticated
  canonical frontend projection.

After mutations, run `validate`, dispatch reconciliation when the change
affects categories/operations, and report the new config version. Stop on an
unknown operation, invalid Calendar mapping, missing queue consumer, or a
request that crosses the advisory-only boundary.
