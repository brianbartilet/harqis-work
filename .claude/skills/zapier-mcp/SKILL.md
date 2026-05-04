Search, enable, and wire Zapier MCP actions into harqis-work workflows or use them directly in conversation. Covers discovery, parameter inference, and optional Celery workflow integration.

## Arguments

`$ARGUMENTS` format (parse left to right):

```
[<task_or_app_description>] [--enable] [--workflow <name>] [--research]
```

| Token | Required | Description |
|---|---|---|
| `task_or_app_description` | Yes | Free-text: the task to accomplish OR the app name to research (e.g. `"send a Slack message"`, `"HubSpot"`, `"post to Airtable when a Jira ticket is created"`). |
| `--enable` | No | After finding a match, immediately enable the action on the Zapier MCP server without asking again. |
| `--workflow <name>` | No | After enabling, scaffold a Celery workflow task that calls the action. Triggers `/create-new-workflow`. |
| `--research` | No | Discovery only — list all matching Zapier apps/actions, do not enable anything. |

---

## Step 0 — Verify Zapier MCP is configured

Before doing anything else, check whether the Zapier MCP server is connected in the current Claude Code session.

Call the Zapier meta-tool to confirm it is reachable:

```
list_enabled_zapier_actions
```

**If the call succeeds:** proceed to Step 1.

**If the call fails or the tool is not found:**

1. Tell the user: _"The Zapier MCP server is not configured in this session. Follow these steps to connect it:"_

2. Print setup instructions:

```
Setup — Zapier MCP Server
─────────────────────────────────────────────────────────────────
1. Go to https://mcp.zapier.com and sign in.
2. Create a new MCP server (or open an existing one).
3. Copy your Personal Integration URL from the "Connect" tab.
4. In Claude Code, run: /update-config
   Add the Zapier MCP server URL when prompted.

   Or add it manually to .claude/settings.json:

   {
     "mcpServers": {
       "zapier": {
         "url": "<your-personal-integration-url>"
       }
     }
   }

5. Restart this Claude Code session so the tools load.

Authentication options:
  • API Key  — generate at mcp.zapier.com → Settings → API Keys
               Header: Authorization: Bearer <key>
  • OAuth    — for multi-user apps (handled by Zapier UI)
─────────────────────────────────────────────────────────────────
```

3. Stop here. Do not continue until the user confirms the server is connected.

---

## Step 1 — Check for existing harqis-work coverage

Before touching Zapier, check whether the requested integration already exists natively.

**Check the MCP server registrations:**

```bash
grep -i "<app_keyword>" mcp/server.py
```

**Check the apps/ directory:**

```bash
ls apps/ | grep -i "<app_keyword>"
```

**Check the Kanban MCP bridge:**

```bash
grep -i "<app_keyword>" agents/projects/agent/tools/mcp_bridge.py
```

If a native integration exists:
- Tell the user which `apps/<name>` module covers the task and what MCP tools are available.
- Ask: _"The `<app_name>` integration already exists in harqis-work with these tools: [list]. Do you still want to search Zapier, or would you like to use the existing integration instead?"_
- If the user wants to continue with Zapier anyway (e.g. for a different action not covered), proceed.
- If the user wants to use the existing integration, stop here and suggest the relevant tools.

---

## Step 2 — Discover matching Zapier actions

Call the Zapier meta-tool to search for actions matching the task description:

```
discover_zapier_actions(query="<task_or_app_description>")
```

Parse the results. For each returned action, extract:
- **App name** — the service it targets (Slack, Airtable, HubSpot, etc.)
- **Action name** — what the action does (Send Message, Create Record, Find Contact, etc.)
- **Action type** — read (query/search) or write (create/update/trigger)
- **Action ID** — needed for enabling and executing

Present findings as a table:

```
Matching Zapier actions for: "<task_or_app_description>"

 #  App            Action                     Type    Action ID
──────────────────────────────────────────────────────────────────
 1  Slack          Send Channel Message        write   slack_send_channel_message
 2  Slack          Send Direct Message         write   slack_send_direct_message
 3  Slack          Find Message                read    slack_find_message
 4  Microsoft Teams  Send a Message            write   teams_send_message
 5  Discord        Send Channel Message        write   discord_send_channel_message
    (already in harqis-work natively ↑)
```

If no results are returned, broaden the search with synonyms or a shorter keyword, then try again. If still empty, tell the user and suggest alternative search terms.

---

## Step 3 — Evaluate and select

If `--research` was passed: stop here. Print the full discovery table and summarise which apps look most suitable for the task. Do not enable anything.

Otherwise, ask the user (unless `--enable` was passed, in which case auto-select the best match):

```
Which action would you like to enable?
Enter a number from the table above, or type 'none' to cancel.
```

**Selection criteria when auto-selecting (`--enable`):**
1. Prefer an exact app name match over a partial match
2. Prefer write actions when the task description uses verbs like "send", "create", "post", "update"
3. Prefer read actions when the task uses verbs like "find", "search", "get", "check", "list"
4. Exclude any action already available natively in harqis-work (flag it but don't block)

---

## Step 4 — Enable the action on the Zapier MCP server

Call:

```
enable_zapier_action(action_id="<selected_action_id>")
```

Confirm the action is now enabled:

```
list_enabled_zapier_actions
```

Verify the selected action appears in the list. If it does not, retry once with the same action_id and report the error if it still fails.

---

## Step 5 — Infer and map parameters

Every Zapier action has required and optional parameters. Infer their values from context before asking the user for anything.

**Sources to infer from (in priority order):**

1. **`$ARGUMENTS` / task description** — extract explicit values (e.g. "send to #general" → `channel = "#general"`)
2. **Workflow context** — if the action is being added to a workflow, read the other steps' output fields and map them to this action's input params
3. **`apps_config.yaml`** — for service-level defaults (e.g. the Slack workspace URL is often in config)
4. **Previous conversation** — any values the user already mentioned

Build a parameter map:

```
Action: slack_send_channel_message
Parameters:
  channel   = "#general"                (inferred from task description)
  message   = <output of previous step> (inferred from workflow context)
  username  = "harqis-bot"              (suggested default)
  icon_url  = (not set — optional)
```

For any required parameter that cannot be inferred, ask the user explicitly — one question per missing required param. Do not ask about optional params unless the task clearly requires them.

---

## Step 6 — Test the action directly (optional)

If the task is ad-hoc (no `--workflow` flag) or the user asks to test it, execute the action in the current conversation using the appropriate Zapier meta-tool.

For **write** actions:

```
execute_zapier_write_action(
  action_id="<action_id>",
  params={"channel": "#general", "message": "Hello from harqis!"}
)
```

For **read** actions:

```
execute_zapier_read_action(
  action_id="<action_id>",
  params={"query": "<search_term>"}
)
```

Report the result to the user. If execution fails:
- Check whether all required parameters were provided
- Check whether the Zapier account has the target app connected at zapier.com
- Suggest the user visit mcp.zapier.com → History tab for the error detail

---

## Step 7 — Celery workflow integration (--workflow flag only)

If `--workflow <name>` was passed, scaffold a workflow task that calls the Zapier action via the **Zapier REST API** so it can be scheduled or triggered by Celery Beat without an active Claude session.

### 7a — Determine the REST execution endpoint

Zapier actions enabled via MCP can also be called programmatically:

```
POST https://actions.zapier.com/api/v1/exposed/<action_id>/execute/
Authorization: Bearer <ZAPIER_API_KEY>
Content-Type: application/json

{"data": {"channel": "#general", "message": "..."}}
```

The `action_id` is the same one used in Steps 4–6.

### 7b — Add Zapier to apps_config.yaml if not present

```bash
grep -n "ZAPIER" apps_config.yaml
```

If not present, append:

```yaml
ZAPIER:
  app_id: 'zapier'
  client: 'rest'
  parameters:
    base_url: 'https://actions.zapier.com/api/v1/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 30
    stream: False
  app_data:
    api_key: ${ZAPIER_API_KEY}
  return_data_only: True
```

### 7c — Add ZAPIER_API_KEY to .env/apps.env if not present

```bash
grep -n "ZAPIER_API_KEY" .env/apps.env
```

If not found, append:

```
# ZAPIER
ZAPIER_API_KEY=
```

Remind the user to fill in the key from mcp.zapier.com → Settings → API Keys.

### 7d — Invoke /create-new-workflow

Call `/create-new-workflow <name>` with the following context pre-answered:
- **Apps needed:** zapier (for the HTTP call), plus any harqis-work apps involved in prior/subsequent steps
- **Step that calls Zapier:** uses `CONFIG_MANAGER.get('ZAPIER')` and posts to the action endpoint
- **Parameters:** already mapped in Step 5

In the generated task file, the Zapier call follows this pattern:

```python
import requests
from apps.apps_config import CONFIG_MANAGER

def _call_zapier_action(action_id: str, data: dict) -> dict:
    cfg = CONFIG_MANAGER.get('ZAPIER')
    url = f"{cfg['parameters']['base_url']}exposed/{action_id}/execute/"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {cfg['app_data']['api_key']}"},
        json={"data": data},
        timeout=cfg['parameters']['timeout'],
    )
    resp.raise_for_status()
    return resp.json()
```

---

## Step 8 — Summary and checklist

Print at the end:

```
Zapier MCP integration complete.

  Action enabled : <app_name> — <action_name>  (<action_id>)
  Enabled tools  : <n> total on your Zapier MCP server
  Test result    : <passed / skipped>

  Workflow task  : <path> (if --workflow was used)

  Next steps:
  [ ] Confirm ZAPIER_API_KEY is set in .env/apps.env (if workflow integration added)
  [ ] Visit mcp.zapier.com → History tab to monitor action executions
  [ ] If the target app is not connected to your Zapier account, connect it at zapier.com/app/connections
```

---

## Decision guide — when to use Zapier MCP vs native apps/

| Situation | Use |
|---|---|
| App already in `apps/` (Slack, Discord, Trello, Jira, etc.) | Native harqis-work app — more control, lower latency |
| App exists in `apps/` but the specific action isn't implemented yet | Zapier MCP for now; note it as a gap to fill natively later |
| App not in `apps/` and building a full native integration is not justified | Zapier MCP — fastest path |
| Research phase — exploring what's available before deciding | Zapier MCP `--research` flag |
| Workflow needs 2,000+ different apps with minimal config | Zapier MCP — its catalogue covers far more than `apps/` |
| Task requires real-time / sub-second response | Native app preferred — Zapier adds ~1–3s latency per call |
| Task uses 2 Zapier tasks per call and quota is a concern | Native app preferred |

---

## Agentic mode tool reference

These Zapier meta-tools are available when Zapier MCP is connected in Agentic mode:

| Tool | Purpose | Key params |
|---|---|---|
| `discover_zapier_actions` | Search available apps and actions | `query` (string) |
| `enable_zapier_action` | Add an action to your MCP server | `action_id` (string) |
| `list_enabled_zapier_actions` | List all currently enabled actions | — |
| `execute_zapier_write_action` | Run a write (create/send/update) action | `action_id`, `params` (dict) |
| `execute_zapier_read_action` | Run a read (search/find/get) action | `action_id`, `params` (dict) |
| `disable_zapier_action` | Remove an action from your MCP server | `action_id` |
| `get_zapier_action_schema` | Get the full parameter schema for an action | `action_id` |

Use `get_zapier_action_schema` whenever the parameter mapping in Step 5 is ambiguous — it returns the exact required/optional field list with types and descriptions.
