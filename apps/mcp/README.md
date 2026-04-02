# apps/mcp — MCP Server for harqis-work

## What is MCP?

**Model Context Protocol (MCP)** is an open standard by Anthropic that lets AI models (like Claude) call
external tools, read resources, and use prompt templates through a standardized interface.

Instead of you writing code to call an API and feeding the result to Claude, MCP flips the model:
Claude decides *when* and *which* tool to call based on the conversation, calls it autonomously, and
reasons over the live result.

```
Claude (AI) ←──── MCP protocol ────→ MCP Server ←───→ Your app services
```

### Key concepts

| Concept | What it is |
|---------|-----------|
| **Tool** | A callable function Claude can invoke (like a REST endpoint for the AI) |
| **Resource** | Read-only data Claude can query (files, DB records, config) |
| **Prompt** | A reusable prompt template the AI can select and fill |
| **Transport** | How Claude and the server communicate — `stdio` (local) or `HTTP/SSE` (remote) |

### MCP vs regular API calls

| Regular API integration | MCP tool |
|------------------------|----------|
| You decide when to call it | Claude decides when it's relevant |
| Fixed call sequence in code | Claude reasons about which tool fits |
| Result needs manual wiring into prompt | Claude reads the result and continues reasoning |

---

## This server

`apps/mcp/server.py` is the entry point. It creates a `FastMCP` instance named `harqis-work` and
registers tool modules from `references/tools/`. Each module exposes a `register_<app>_tools(mcp)`
function that decorates service methods as `@mcp.tool()`.

```
apps/mcp/
├── server.py                     # Entry point — creates FastMCP, registers tools, runs server
├── claude_desktop_config.json    # Config snippet for Claude Desktop
├── references/
│   └── tools/
│       └── oanda.py              # OANDA tool registrations (wraps apps/oanda services)
└── tests/
```

---

## Available tools

### OANDA (`references/tools/oanda.py`)

Wraps `apps/oanda/references/web/api/` services. Requires valid `OANDA` section in `apps_config.yaml`.

| Tool | Args | Returns |
|------|------|---------|
| `get_oanda_accounts` | — | List of account IDs and tags |
| `get_oanda_account_details` | `account_id` | Balance, NAV, currency, margin rate, open counts |
| `get_oanda_open_trades` | `account_id` | All currently open trades |
| `get_oanda_trades` | `account_id`, `instrument?`, `count?` | Trade history with optional filters |

**Example prompts you can give Claude once connected:**

- *"What is the current balance on my OANDA account?"*
- *"Show me all open EUR/USD trades."*
- *"How many open positions do I have right now?"*
- *"Get the last 10 trades for instrument GBP_USD."*

---

## Running the server

```sh
# From repo root, activate your venv first
python apps/mcp/server.py
```

The server starts in `stdio` mode (the default for local Claude Desktop connections). You will see
startup logs confirming which tools were registered.

---

## Connecting to Claude Desktop

1. Open **Claude Desktop** → Settings → Developer → **Edit Config**
2. Merge the following into your `claude_desktop_config.json`
   (the full snippet is also at `apps/mcp/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "harqis-work": {
      "command": "C:\Users\brian\GIT\harqis-work\.venv\Scripts\python.exe",
      "args": ["C:\Users\brian\GIT\harqis-work\apps\mcp\server.py"]
    }
  }
}
```

3. **Restart Claude Desktop** — the harqis-work tools will appear in the tools panel.

---

## Connecting to Claude Code (this CLI)

Add the server to your Claude Code MCP config:

```sh
claude mcp add harqis-work \
  "C:\Users\brian\GIT\harqis-work\.venv\Scripts\python.exe" \
  "C:\Users\brian\GIT\harqis-work\apps\mcp\server.py"
```

Or add it manually to `~/.claude/settings.json` under `mcpServers`.

---

## Adding a new app's tools

1. Create `apps/mcp/references/tools/<app_name>.py`:

```python
import logging
from mcp.server.fastmcp import FastMCP
from apps.<app_name>.config import CONFIG
from apps.<app_name>.references.web.api.<service> import ApiService<App>

logger = logging.getLogger("harqis-mcp.<app_name>")

def register_<app_name>_tools(mcp: FastMCP):

    @mcp.tool()
    def my_tool(param: str) -> dict:
        """Describe what Claude should know about this tool."""
        logger.info("Tool called: my_tool param=%s", param)
        service = ApiService<App>(CONFIG)
        return service.some_method(param)
```

2. Import and register in `server.py`:

```python
from apps.mcp.references.tools.<app_name> import register_<app_name>_tools

register_<app_name>_tools(mcp)
```

### Recommended next integrations

| App | Suggested tools |
|-----|----------------|
| `scryfall` | `search_card`, `get_card_price` |
| `ynab` | `get_budget_summary`, `list_transactions` |
| `google_apps` | `get_calendar_events`, `append_to_sheet` |
| `tcg_mp` | `get_order_status`, `list_active_listings` |

---

## Logging

The server uses Python's standard `logging` module with logger hierarchy `harqis-mcp.*`:

- `harqis-mcp` — server lifecycle (startup, tool count)
- `harqis-mcp.oanda` — per-call logs for every OANDA tool invocation

Logs go to stderr (visible in Claude Desktop's MCP log viewer and in the terminal when running manually).
To increase verbosity, change `logging.basicConfig(level=logging.INFO)` to `logging.DEBUG` in `server.py`.
