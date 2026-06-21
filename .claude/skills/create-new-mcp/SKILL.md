---
name: create-new-mcp
description: >
  Build or extend the MCP tool surface for an existing app under apps/* by wrapping its
  service-layer endpoints (references/web/api/*) as @mcp.tool() functions. This skill is the
  single source of truth for the MCP layer: it audits which public service methods are not yet
  exposed, proposes the gaps, generates the wrappers, and wires registration (mcp/server.py
  APP_REGISTRARS + the Kanban bridge _APP_LOADERS) and docs (apps/<app>/README.md + mcp/README.md).
  It forms a two-way feedback loop with /create-new-service-app: that skill delegates its MCP step
  here, and this skill loops back to it whenever a needed endpoint is missing from the service layer.
  Trigger phrases (non-exhaustive): "create mcp for <app>", "add mcp tools", "expand the mcp surface
  for <app>", "wrap <app> endpoints as mcp tools", "expose <app> in mcp", "mcp coverage for <app>",
  "extend mcp capabilities of <app>".
  Do NOT use to create a brand-new app integration from scratch — that's /create-new-service-app
  (which then delegates the MCP layer back to this skill).
---

Build or extend the MCP tool surface for an **existing** app under `apps/*`, wrapping its
service-layer endpoints (`references/web/api/*.py`) as `@mcp.tool()` functions.

This skill **owns the MCP layer** for the whole repo. `/create-new-service-app` delegates its
MCP step to this skill, and this skill loops back to `/create-new-service-app` when the app or a
needed endpoint doesn't exist yet. See **The feedback loop** at the end.

## Arguments

`$ARGUMENTS` format (parse left to right):

```
<app_name> [method_or_resource ...] [--all] [--check]
```

| Token | Required | Description |
|---|---|---|
| `app_name` | Yes | snake_case app under `apps/`, e.g. `ynab`, `tcg_mp`, `scryfall` |
| `method_or_resource` | No | Limit work to specific service methods or resource files (e.g. `transactions payees`). Omit to audit the whole app. |
| `--all` | No | Skip the confirm step — wrap every unwrapped public service method found. |
| `--check` | No | Audit only: print the coverage gap (wrapped vs unwrapped) and stop. Write nothing. |

---

## Step 0 — Resolve the target app (loop-back gate)

Check that `apps/<app_name>/` exists and contains `references/web/api/*.py` service classes.

- **App directory missing** → this is a brand-new integration. Stop and hand off:
  invoke `/create-new-service-app <app_name>` to scaffold the app first. That skill will call
  back into this one for the MCP layer. Do **not** scaffold the app yourself here.
- **App exists but has no `references/web/api/` service classes** → there's nothing to wrap yet.
  Tell the user and hand off to `/create-new-service-app <app_name> <spec_or_url>` to build the
  service layer, then resume here.

Confirm `apps/<app_name>/mcp.py` exists. If not, you'll create it in Step 3 (a partially-built app
can have a service layer but no `mcp.py` yet).

---

## Step 1 — Audit the service layer vs existing tools

Read every `apps/<app_name>/references/web/api/*.py` and enumerate the **public** service methods
(skip `__init__`, `initialize`, and `_`-prefixed helpers). For each, note the class, method name,
signature, and one-line purpose from its body/docstring.

Then read `apps/<app_name>/mcp.py` (if present) and list the already-registered `@mcp.tool()`
functions and which service method each calls.

Compute the **coverage gap**: public service methods with no corresponding tool. Group them by
resource (service file). Note any methods that are intentionally internal (pure helpers, auth,
pagination primitives) and should NOT become tools.

If `--check`, print the gap table (`service.method → wrapped? → proposed tool name`) and stop.

---

## Step 2 — Propose coverage and confirm

Present the proposed new tools as a compact table: `proposed_tool_name | wraps | destructive?`.
Map each gap method to a tool name using the **Naming** rules below. Flag any
create/update/delete/remove method as **destructive** (its docstring must say so).

If the user's requirements reference a capability that has **no matching service method**
(e.g. "delete a transaction" but the service only has get/create):

> **Loop back to the service layer.** Stop and hand off to
> `/create-new-service-app <app_name>` to add the missing service method(s) to
> `references/web/api/*`, then resume this skill from Step 1. The service layer is the single
> owner of endpoints — never add API-calling methods to `mcp.py` itself.

Unless `--all` or a specific method list was given, ask the user to confirm the proposed tool set
(one round, concise). Then proceed.

---

## Step 3 — Write / extend `apps/<app_name>/mcp.py`

Match the existing app conventions exactly. Reference implementations: `apps/ynab/mcp.py`,
`apps/tcg_mp/mcp.py`, `apps/scryfall/mcp.py`.

If creating the file, use this skeleton:

```python
import logging

from mcp.server.fastmcp import FastMCP
from apps.<app_name>.config import CONFIG
from apps.<app_name>.references.web.api.<resource> import ApiService<App><Resource>

logger = logging.getLogger("harqis-mcp.<app_name>")


def register_<app_name>_tools(mcp: FastMCP):

    @mcp.tool()
    def <verb>_<app_name>_<resource>(<args>) -> <list[dict] | dict>:
        """<One-line description Claude reads to decide when to call this.>

        Args:
            <arg>: <what it is; note formats/units/enums>
        """
        logger.info("Tool called: <verb>_<app_name>_<resource> <arg>=%s", <arg>)
        service = ApiService<App><Resource>(CONFIG)
        result = service.<method>(<args>)
        output = result if isinstance(result, dict) else (result.__dict__ if hasattr(result, "__dict__") else {})
        logger.info("<verb>_<app_name>_<resource> done")
        return output
```

When **extending** an existing `mcp.py`, add the new tools inside the existing
`register_<app_name>_tools` function (don't create a second register function), add any new
service imports, and group related tools with a short `# --- <section> ---` comment as in
`apps/ynab/mcp.py`.

Every `@mcp.tool()` MUST have:
- A descriptive docstring with an `Args:` section for every non-trivial parameter.
- `logger.info(...)` at entry **and** on result.
- A defensive serialization of the return value: `list[dict]` (serialize DTOs via `.__dict__`)
  or `dict`. Never return a raw DTO/Response object.
- For write tools that wrap a pass-through service method (body-in), build the API's body wrapper
  in the tool (e.g. `{"transaction": {...}}`) — see `apps/ynab/mcp.py`.

**Naming:** `<verb>_<app_name>_<resource>` — verbs `get` / `list` / `search` / `create` /
`update` / `delete` / `analyze`. Keep names unique across the whole server (they share one
namespace). Mark destructive ops clearly in the docstring.

---

## Step 4 — Register in `mcp/server.py`

Read `mcp/server.py`. Registration is the `APP_REGISTRARS` list of
`(label, module_path, func_name)` tuples — **not** an inline import. If the app is **not**
already in the list, add a tuple (match the column alignment of neighbours):

```python
    ("<Label>",          "apps.<app_name>.mcp",     "register_<app_name>_tools"),
```

If the app already has a tuple (you only added tools to an existing `mcp.py`), **make no change** —
the existing registration picks up the new tools automatically.

---

## Step 5 — Register in the Kanban bridge

Read `agents/projects/agent/tools/mcp_bridge.py`. If `<app_name>` is not already a key in the
`_APP_LOADERS` dict, add it (alphabetical by key, preserve column alignment):

```python
    "<app_name>":  "apps.<app_name>.mcp.register_<app_name>_tools",
```

If the key already exists, make no change.

---

## Step 6 — Update `apps/<app_name>/README.md`

Update (or add) the **## MCP Tools** section — a table of `tool name | description` covering the
full current tool set (existing + new). Mark destructive tools. If amounts/IDs/date formats matter,
add a one-line note (see `apps/ynab/README.md`). Keep it in sync with `mcp.py` exactly.

---

## Step 7 — Update `mcp/README.md`

Read `mcp/README.md`. Add or update the app's section (alphabetical) with a tool table and 2–3
example prompts in italics, mirroring the existing app sections.

---

## Step 8 — Validate

1. **Compile:** `python -m py_compile apps/<app_name>/mcp.py` plus any service files you touched.
2. **Register-check** (the config loader defaults to a non-existent `_dev` file — pass the real
   one explicitly):

   ```bash
   APP_CONFIG_FILE=apps_config.yaml python -c "
   from mcp.server.fastmcp import FastMCP
   from apps.<app_name>.mcp import register_<app_name>_tools
   import asyncio
   m = FastMCP('t'); register_<app_name>_tools(m)
   print(sorted(t.name for t in asyncio.run(m.list_tools())))
   "
   ```

   Confirm the new tool names appear and there are no import errors.
3. **Optional live smoke:** call one or two **read-only** new tools' underlying service methods
   against real config to confirm the endpoint/auth path works. Skip destructive calls. If you hit
   a 401/placeholder token, report it as a config gap (env var not set) — not a code bug.

---

## Step 9 — Tests (optional but encouraged)

If the app's `tests/` follow the live-integration pattern, add `@pytest.mark.smoke` tests for
read-only new methods and `@pytest.mark.skip` tests for destructive ones (mirror the existing test
files — e.g. `apps/ynab/tests/test_transactions.py`). Verify they at least collect:
`python -m pytest apps/<app_name>/tests/ --collect-only -q`.

---

## Step 10 — Remind the user

Print verbatim:

```
MCP tools updated for <app_name>.
Next steps:
  [ ] (if a tuple was added to mcp/server.py) restart / reconnect the MCP server
  [ ] Reconnect in Claude Code: /mcp → harqis-work → Reconnect  (tool list is cached at connect)
  [ ] (if any new env var is needed) fill it in .env/apps.env
```

---

## The feedback loop (how this dovetails with /create-new-service-app)

```
/create-new-service-app  ──(builds service layer)──▶  delegates MCP step  ──▶  /create-new-mcp
        ▲                                                                            │
        └────────────  loops back when an endpoint is missing  ◀────────────────────┘
```

- **/create-new-service-app → /create-new-mcp:** after the service layer + DTOs + config exist,
  that skill calls `/create-new-mcp <app_name> --all` to generate the MCP layer and registration,
  instead of hand-rolling tools. /create-new-mcp is the single source of truth for `mcp.py`
  conventions, `APP_REGISTRARS`, `_APP_LOADERS`, and the MCP docs.
- **/create-new-mcp → /create-new-service-app:** when the target app (or a required endpoint) is
  missing, this skill hands off to `/create-new-service-app` to build it, then resumes wrapping.

Net effect: endpoints are always owned by the service layer; the MCP surface is always generated
the same way; neither side duplicates the other's logic.

---

## Quality checklist (verify before finishing)

- [ ] Step 0 loop-back honoured (handed off to /create-new-service-app if app/endpoint missing)
- [ ] Coverage gap audited; internal helpers intentionally excluded
- [ ] New tools live inside the single `register_<app_name>_tools` function
- [ ] Every tool: docstring + `Args:` + entry/result logs + defensive return serialization
- [ ] Destructive tools (create/update/delete/remove) flagged in their docstrings
- [ ] Tool names unique across the server and follow `<verb>_<app>_<resource>`
- [ ] `mcp/server.py` `APP_REGISTRARS` tuple present (added only if the app was new to it)
- [ ] `mcp_bridge.py` `_APP_LOADERS` key present (added only if missing)
- [ ] `apps/<app_name>/README.md` MCP Tools table matches `mcp.py`
- [ ] `mcp/README.md` app section updated
- [ ] Register-check passes with `APP_CONFIG_FILE=apps_config.yaml`
- [ ] User reminded to reconnect the MCP server
