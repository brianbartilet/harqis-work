# mcp — MCP Server for harqis-work

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

`mcp/server.py` is the entry point. It creates a `FastMCP` instance named `harqis-work` and
registers tool modules from each app. Each app exposes a `register_<app>_tools(mcp)` function in
`apps/<app>/mcp.py` that decorates service calls as `@mcp.tool()`.

```
mcp/
├── server.py                              # Entry point — creates FastMCP, registers tools, runs server
├── claude_desktop_config.json.template   # Template — render per-machine (gitignored when rendered)
└── README.md                              # This file

apps/
├── oanda/mcp.py                      # OANDA forex tools
├── ynab/mcp.py                       # YNAB budgeting tools
├── google_apps/mcp.py                # Google Calendar, Keep, and Gmail tools
├── tcg_mp/mcp.py                     # TCG Marketplace tools
├── echo_mtg/mcp.py                   # Echo MTG inventory tools
├── scryfall/mcp.py                   # Scryfall card database tools
└── telegram/mcp.py                   # Telegram bot tools
```

Tool bindings live alongside the app they wrap — each `apps/<app>/mcp.py` is self-contained and
imports only from its own app's services and config.

---

## Available tools

### OANDA (`apps/oanda/mcp.py`)

Wraps `apps/oanda/references/web/api/` services. Requires valid `OANDA` section in `apps_config.yaml`.

| Tool | Args | Returns |
|------|------|---------|
| `get_oanda_accounts` | — | List of account IDs and tags |
| `get_oanda_account_details` | `account_id` | Balance, NAV, currency, margin rate, open counts |
| `get_oanda_open_trades` | `account_id` | All currently open trades |
| `get_oanda_trades` | `account_id`, `instrument?`, `count?` | Trade history with optional filters |

**Example prompts:**
- *"What is the current balance on my OANDA account?"*
- *"Show me all open EUR/USD trades."*
- *"Get the last 10 trades for GBP_USD."*

---

### YNAB (`apps/ynab/mcp.py`)

Wraps `apps/ynab/references/web/api/` services. Requires valid `YNAB` section in `apps_config.yaml`.

| Tool | Args | Returns |
|------|------|---------|
| `get_ynab_budgets` | — | List of all YNAB budgets |
| `get_ynab_budget_summary` | `budget_id` | Budget details |
| `get_ynab_accounts` | `budget_id` | Accounts in a budget |
| `get_ynab_categories` | `budget_id` | Category groups and categories |
| `get_ynab_transactions` | `budget_id` | All transactions in a budget |
| `get_ynab_account_transactions` | `budget_id`, `account_id` | Transactions for a specific account |
| `get_ynab_user` | — | YNAB user profile |

**Example prompts:**
- *"What are my current YNAB budget categories and balances?"*
- *"Show me all transactions this month."*
- *"How much have I spent on dining this month?"*

---

### Gemini (`apps/gemini/mcp.py`)

Wraps `apps/gemini/references/web/api/` services. Requires valid `GEMINI` section in `apps_config.yaml`.

| Tool | Args | Returns |
|------|------|---------|
| `list_gemini_models` | `page_size?` | List of available Gemini model dicts |
| `get_gemini_model` | `model_name` | Single model metadata |
| `gemini_generate_content` | `prompt`, `model?`, `temperature?`, `max_output_tokens?`, `system_instruction?` | Candidates list with generated text |
| `gemini_count_tokens` | `prompt`, `model?` | Token count for the prompt |
| `gemini_embed_content` | `text`, `model?`, `task_type?` | Embedding vector (values list) |
| `gemini_batch_embed_contents` | `texts`, `model?`, `task_type?` | List of embedding vectors |

**Example prompts:**
- *"Ask Gemini to summarise this text for me."*
- *"How many tokens will this prompt use with Gemini Flash?"*
- *"Generate a text embedding for this sentence using Gemini."*

---

### Grok (`apps/grok/mcp.py`)

Wraps xAI Grok via the OpenAI-compatible SDK (`https://api.x.ai/v1`). Requires valid `GROK` section in `apps_config.yaml`.

| Tool | Args | Returns |
|------|------|---------|
| `grok_chat` | `prompt`, `model?`, `system?`, `temperature?`, `max_tokens?` | `{id, model, output_text, finish_reason, usage}` |
| `grok_web_search` | `query`, `model?` | `{id, model, output_text, finish_reason, usage}` — answer grounded in live web results |
| `grok_x_search` | `query`, `model?` | `{id, model, output_text, finish_reason, usage}` — answer grounded in X (Twitter) posts |
| `grok_list_models` | — | List of available Grok model dicts |
| `grok_embed` | `text`, `model?` | `{model, embedding_dims, embedding, usage}` — 4096-dim vector |

**Example prompts:**
- *"Ask Grok what happened in AI news today."*
- *"Use grok_web_search to find the current Bitcoin price."*
- *"Search X posts about the latest Grok release using grok_x_search."*
- *"Generate an embedding for this sentence with Grok."*

---

### Perplexity (`apps/perplexity/mcp.py`)

Wraps Perplexity Sonar — chat completions with built-in live web search and inline citations, a direct search endpoint, embeddings, and async deep research. [API docs](https://docs.perplexity.ai/). Requires valid `PERPLEXITY` section in `apps_config.yaml`.

| Tool | Args | Returns |
|------|------|---------|
| `perplexity_chat` | `prompt`, `model?`, `system?`, `temperature?`, `max_tokens?`, `search_domain_filter?`, `search_recency_filter?` | `{id, model, output_text, citations, finish_reason, usage}` |
| `perplexity_submit_async` | `prompt`, `model?`, `system?`, `max_tokens?` | Async request envelope with `id` |
| `perplexity_get_async` | `request_id` | Async result (status + completion if ready) |
| `perplexity_list_async` | — | List of pending/completed async requests |
| `perplexity_search` | `query`, `max_results?`, `search_domain_filter?`, `search_recency_filter?`, `language?` | `{query, results, count}` |
| `perplexity_embed` | `text`, `model?` | `{model, embedding_dims, embedding, usage}` |
| `perplexity_list_models` | — | List of model dicts |

**Example prompts:**
- *"Ask Perplexity what tech news happened today and cite the sources."*
- *"Use perplexity_search to find the latest research papers on retrieval-augmented generation."*
- *"Run perplexity_submit_async with sonar-deep-research on '...' and check it later."*

---

### Google Apps (`apps/google_apps/mcp.py`)

Wraps `apps/google_apps/references/web/api/` services.

Config sections required in `apps_config.yaml`:
- `GOOGLE_APPS` — Calendar (uses `credentials.json` / `storage.json`)
- `GOOGLE_KEEP` — Keep notes (uses `credentials-ha.json` / `storage-ha.json`)
- `GOOGLE_GMAIL` — Gmail (uses `credentials.json` / `storage-gmail.json`)

| Tool | Args | Returns |
|------|------|---------|
| `get_google_calendar_events_today` | `event_type?` | Today's calendar events (ALL/ALL_DAY/NOW/SCHEDULED/UPCOMING_UNTIL_EOD) |
| `get_google_calendar_holidays` | `country_code?` | Public holidays for a country |
| `list_google_keep_notes` | `filter?` | List Keep notes (non-trashed by default) |
| `get_google_keep_note` | `name` | Get a specific Keep note by resource name |
| `create_google_keep_note` | `title`, `text` | Create a new Keep note |
| `get_gmail_recent_emails` | `max_results?`, `query?` | Recent emails with subject, sender, date, snippet, body |
| `search_gmail` | `query`, `max_results?` | Search Gmail using Gmail search syntax |

**Gmail OAuth note:** On first use, the Gmail tool will open a browser to complete the OAuth consent
flow and write the token to `storage-gmail.json`. Subsequent calls use the cached token silently.

**Example prompts:**
- *"What meetings do I have today?"*
- *"Is today a public holiday in the Philippines?"*
- *"List all my Google Keep notes."*
- *"Create a note titled 'Shopping list' with text 'Milk, eggs, bread'."*
- *"Show me my last 10 emails."*
- *"Find any unread emails from GitHub."*
- *"Search my Gmail for emails with attachments from this week."*

---

### TCG Marketplace (`apps/tcg_mp/mcp.py`)

Wraps `apps/tcg_mp/references/web/api/` services. Requires valid `TCG_MP` section in `apps_config.yaml`.

| Tool | Args | Returns |
|------|------|---------|
| `search_tcg_card` | `card_name`, `page?`, `items?` | Card search results from TCG Marketplace |
| `get_tcg_orders` | `status?` | Orders filtered by status (default: PENDING_DROP_OFF) |
| `get_tcg_order_detail` | `order_id` | Full order details |
| `get_tcg_listings` | — | All active listings for the configured user |

**Valid order statuses:** `ALL`, `PENDING_DROP_OFF`, `SHIPPED`, `COMPLETED`, `CANCELLED`,
`NOT_RECEIVED`, `DROPPED`, `ARRIVED_BRANCH`, `PICKED_UP`, `PENDING_PAYMENT`

**Example prompts:**
- *"How many pending orders do I have on TCG Marketplace?"*
- *"Show me all my active card listings."*
- *"Search for Llanowar Elves on TCG Marketplace."*

---

### Echo MTG (`apps/echo_mtg/mcp.py`)

Wraps `apps/echo_mtg/references/web/api/inventory`. Requires valid `ECHO_MTG` section in `apps_config.yaml`.

| Tool | Args | Returns |
|------|------|---------|
| `get_echo_mtg_portfolio_stats` | — | Portfolio value, collection size, and stats |
| `get_echo_mtg_collection` | `limit?`, `tradable_only?` | Card collection inventory |
| `search_echo_mtg_card` | `emid`, `tradable_only?` | Search inventory by Echo MTG ID |

**Example prompts:**
- *"What is the total value of my MTG collection?"*
- *"Show me my tradable cards."*

---

### Scryfall (`apps/scryfall/mcp.py`)

Wraps `apps/scryfall/references/web/api/` services. Requires valid `SCRYFALL` section in `apps_config.yaml`.

| Tool | Args | Returns |
|------|------|---------|
| `get_scryfall_card` | `card_guid` | Full card metadata (prices, legality, art, etc.) |
| `get_scryfall_bulk_data_info` | — | Available Scryfall bulk data download metadata |

**Example prompts:**
- *"Get the Scryfall metadata for card UUID e3285e6b-3e79-4d7c-bf96-d920f973b122."*
- *"What bulk data files does Scryfall offer?"*

---

### Telegram (`apps/telegram/mcp.py`)

Wraps `apps/telegram/references/web/api/` services. Requires valid `TELEGRAM` section in `apps_config.yaml`.

| Tool | Args | Returns |
|------|------|---------|
| `get_telegram_bot_info` | — | Bot identity (id, username, first_name) |
| `get_telegram_updates` | `limit?` | Latest pending updates received by the bot |
| `send_telegram_message` | `chat_id`, `text`, `parse_mode?` | Send a message to any chat/user |
| `send_telegram_message_to_default` | `text`, `parse_mode?` | Send to the default configured chat |
| `get_telegram_chat` | `chat_id` | Chat/group/channel metadata |

**Example prompts:**
- *"Send a Telegram message to my default chat saying the build passed."*
- *"What messages has the bot received recently?"*
- *"Get info about my Telegram channel."*

---

## Running the server

```sh
# From repo root, activate your venv first
python mcp/server.py
```

The server starts in `stdio` mode (the default for local Claude Desktop connections). You will see
startup logs confirming which tools were registered.

---

## Connecting to Claude Desktop

`mcp/claude_desktop_config.json` is **gitignored** — it contains machine-specific absolute paths.
Use the template to generate it for your machine:

```sh
# macOS / Linux
export HARQIS_WORK_ROOT="$HOME/GIT/harqis-work"
export HARQIS_VENV_PYTHON="$HARQIS_WORK_ROOT/.venv/bin/python"
envsubst < mcp/claude_desktop_config.json.template > mcp/claude_desktop_config.json

# Windows PowerShell
$env:HARQIS_WORK_ROOT = "$env:USERPROFILE\GIT\harqis-work"
$env:HARQIS_VENV_PYTHON = "$env:HARQIS_WORK_ROOT\.venv\Scripts\python.exe"
(Get-Content mcp\claude_desktop_config.json.template) `
  -replace '\$\{HARQIS_WORK_ROOT\}', $env:HARQIS_WORK_ROOT `
  -replace '\$\{HARQIS_VENV_PYTHON\}', $env:HARQIS_VENV_PYTHON |
  Set-Content mcp\claude_desktop_config.json
```

1. Generate `mcp/claude_desktop_config.json` using the commands above
2. Open **Claude Desktop** → Settings → Developer → **Edit Config**
3. Merge the contents of `mcp/claude_desktop_config.json` into the Claude Desktop config
4. **Restart Claude Desktop** — the harqis-work tools will appear in the tools panel.

---

## Connecting to Claude Code (this CLI)

Add the server to your Claude Code MCP config (adjust paths for your OS):

```sh
# macOS / Linux
claude mcp add harqis-work \
  "$HOME/GIT/harqis-work/.venv/bin/python" \
  "$HOME/GIT/harqis-work/mcp/server.py"

# Windows PowerShell
claude mcp add harqis-work `
  "$env:USERPROFILE\GIT\harqis-work\.venv\Scripts\python.exe" `
  "$env:USERPROFILE\GIT\harqis-work\mcp\server.py"
```

Or add it manually to `~/.claude/settings.json` under `mcpServers`.

---

## Adding a new app's tools

1. Create `apps/<app_name>/mcp.py`:

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

2. Import and register in `mcp/server.py`:

```python
from apps.<app_name>.mcp import register_<app_name>_tools

register_<app_name>_tools(mcp)
```

---

## Logging

The server uses Python's standard `logging` module with logger hierarchy `harqis-mcp.*`:

| Logger | Covers |
|--------|--------|
| `harqis-mcp` | Server lifecycle (startup, tool count) |
| `harqis-mcp.oanda` | Per-call logs for every OANDA tool invocation |
| `harqis-mcp.ynab` | Per-call logs for every YNAB tool invocation |
| `harqis-mcp.google_apps` | Per-call logs for every Google Apps tool invocation |
| `harqis-mcp.tcg_mp` | Per-call logs for every TCG Marketplace tool invocation |
| `harqis-mcp.echo_mtg` | Per-call logs for every Echo MTG tool invocation |
| `harqis-mcp.scryfall` | Per-call logs for every Scryfall tool invocation |
| `harqis-mcp.telegram` | Per-call logs for every Telegram tool invocation |

Logs go to stderr (visible in Claude Desktop's MCP log viewer and in the terminal when running manually).
To increase verbosity, change `logging.basicConfig(level=logging.INFO)` to `logging.DEBUG` in `mcp/server.py`.
