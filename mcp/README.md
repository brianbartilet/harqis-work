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

### Airtable (`apps/airtable/mcp.py`)

Wraps Airtable Web API v0 for spreadsheet-style CRUD over bases, tables, and records. [API docs](https://airtable.com/developers/web/api/introduction). Requires valid `AIRTABLE` section in `apps_config.yaml`.

| Tool | Args | Returns |
|------|------|---------|
| `airtable_whoami` | — | `{id, email, scopes}` |
| `airtable_list_bases` | — | List of `{id, name, permissionLevel}` |
| `airtable_list_tables` | `base_id` | Tables with their fields and views |
| `airtable_list_records` | `base_id`, `table`, `view?`, `filter_by_formula?`, `max_records?`, `page_size?`, `sort?`, `fields?`, `offset?` | `{records, offset, count}` (one page) |
| `airtable_list_all_records` | `base_id`, `table`, `view?`, `filter_by_formula?`, `max_records?`, `sort?`, `fields?` | All matching records (auto-paginated) |
| `airtable_get_record` | `base_id`, `table`, `record_id` | `{id, createdTime, fields}` |
| `airtable_create_records` | `base_id`, `table`, `records`, `typecast?` | List of created records (max 10) |
| `airtable_update_records` | `base_id`, `table`, `records`, `typecast?`, `replace?` | List of updated records (max 10) |
| `airtable_upsert_records` | `base_id`, `table`, `records`, `merge_on`, `typecast?` | Raw API response |
| `airtable_delete_records` | `base_id`, `table`, `record_ids` | Raw API response |
| `airtable_create_table` | `base_id`, `name`, `fields`, `description?` | Created table dict |
| `airtable_create_field` | `base_id`, `table_id`, `name`, `type`, `options?`, `description?` | Created field dict |

**Example prompts:**
- *"List all my Airtable bases."*
- *"Show the first 10 'Done' tasks from base appXYZ table 'Tasks'."*
- *"Add a new lead to base appXYZ table 'Leads' with name 'Acme' and email 'hi@acme.com'."*

---

### Alpha Vantage (`apps/alpha_vantage/mcp.py`)

Wraps the [Alpha Vantage API](https://www.alphavantage.co/documentation/) — stock quotes, FX rates, news & sentiment, fundamentals, technical indicators, crypto, commodities, and US economic indicators. Auth is a single `apikey` query parameter; rate limits are 25 requests/day on the free tier (premium tiers raise the cap). Requires valid `ALPHA_VANTAGE` section in `apps_config.yaml`.

| Tool | Args | Returns |
|------|------|---------|
| `alpha_vantage_global_quote` | `symbol` | Latest price/volume for one ticker |
| `alpha_vantage_realtime_bulk_quotes` | `symbols` (comma-separated, ≤100) | Quotes for many US tickers |
| `alpha_vantage_search_symbol` | `keywords` | Best-match tickers with scores |
| `alpha_vantage_market_status` | — | Open/closed status for global venues |
| `alpha_vantage_time_series_intraday` | `symbol`, `interval?`, `outputsize?` | Intraday OHLCV |
| `alpha_vantage_time_series_daily` | `symbol`, `outputsize?`, `adjusted?` | Daily OHLCV (raw or adjusted) |
| `alpha_vantage_fx_rate` | `from_currency`, `to_currency` | Realtime FX rate (also crypto codes) |
| `alpha_vantage_convert_currency` | `amount`, `from_currency`, `to_currency` | Converted amount + rate |
| `alpha_vantage_fx_intraday` | `from_symbol`, `to_symbol`, `interval?`, `outputsize?` | Intraday FX series |
| `alpha_vantage_fx_daily` | `from_symbol`, `to_symbol`, `outputsize?` | Daily FX series |
| `alpha_vantage_news_sentiment` | `tickers?`, `topics?`, `time_from?`, `time_to?`, `sort?`, `limit?` | News articles with sentiment |
| `alpha_vantage_top_gainers_losers` | — | Daily top gainers/losers/most active |
| `alpha_vantage_insider_transactions` | `symbol` | Recent insider buys/sells |
| `alpha_vantage_earnings_call_transcript` | `symbol`, `quarter?` | Earnings call transcript |
| `alpha_vantage_company_overview` | `symbol` | Description, ratios, metrics |
| `alpha_vantage_etf_profile` | `symbol` | ETF holdings + sector allocation |
| `alpha_vantage_income_statement` | `symbol` | Annual + quarterly income statements |
| `alpha_vantage_balance_sheet` | `symbol` | Annual + quarterly balance sheets |
| `alpha_vantage_cash_flow` | `symbol` | Annual + quarterly cash flows |
| `alpha_vantage_earnings` | `symbol` | Earnings history + EPS |
| `alpha_vantage_dividends` | `symbol` | Dividend events |
| `alpha_vantage_indicator` | `function`, `symbol`, `interval?`, `time_period?`, `series_type?` | Generic technical indicator dispatcher |
| `alpha_vantage_rsi` / `alpha_vantage_sma` / `alpha_vantage_ema` / `alpha_vantage_macd` / `alpha_vantage_bbands` | per-indicator | Common indicators |
| `alpha_vantage_crypto_intraday` | `symbol`, `market?`, `interval?` | Intraday crypto OHLCV |
| `alpha_vantage_crypto_daily` | `symbol`, `market?` | Daily crypto exchange rates |
| `alpha_vantage_commodity` | `name`, `interval?` | Commodity series (WTI, BRENT, COPPER, etc.) |
| `alpha_vantage_economic_indicator` | `name`, `interval?`, `maturity?` | Economic indicator series (GDP, CPI, etc.) |

**Example prompts:**
- *"What's the current EUR to USD exchange rate, and convert 500 EUR to USD."*
- *"Get the latest news sentiment for AAPL and summarise the bullish vs bearish split."*
- *"Show TSLA's RSI(14) on the daily timeframe and tell me if it's overbought."*
- *"Pull the company overview for MSFT and quote the P/E and dividend yield."*

---

### Apify (`apps/apify/mcp.py`)

Wraps the [Apify REST API v2](https://docs.apify.com/api/v2) — a web-scraping platform whose unit of execution is an *actor*. Generic tools call any actor (sync or async); the trends helpers wrap well-known public actors (Google Trends, Instagram, Facebook, TikTok, Reddit) so the model doesn't have to memorise per-actor input schemas. Auth is a Bearer token; runs consume Apify Compute Units. Requires valid `APIFY` section in `apps_config.yaml`.

| Tool | Args | Returns |
|------|------|---------|
| `apify_list_actors` | `my?`, `limit?` | List of actors visible to the token |
| `apify_get_actor` | `actor_id` | Full actor metadata |
| `apify_run_actor_sync` | `actor_id`, `input_payload?`, `timeout_secs?`, `limit?` | Dataset items from a sync run |
| `apify_run_actor` | `actor_id`, `input_payload?`, `timeout_secs?` | Async run object (poll later) |
| `apify_list_runs` | `status?`, `limit?` | Recent runs across the account |
| `apify_get_run` | `run_id` | Run status + dataset/store IDs |
| `apify_get_dataset_items` | `dataset_id`, `limit?`, `offset?`, `fields?` | Records from a dataset |
| `apify_google_trends` | `keywords`, `geo?`, `timeframe?` | Trending interest per keyword/region/window |
| `apify_instagram_hashtag` | `hashtags`, `results_limit?` | Recent IG posts per hashtag |
| `apify_facebook_posts` | `page_urls_or_queries`, `results_limit?` | Recent FB posts |
| `apify_tiktok` | `hashtags_or_keywords`, `results_per_page?` | Recent TikTok videos |
| `apify_reddit` | `keywords`, `subreddits?`, `sort?`, `max_items?` | Reddit search hits |
| `apify_aggregate_trends` | `query`, `platforms?`, `location?`, `timeframe?`, `per_platform_limit?` | Cross-platform normalised items |
| `apify_default_actors` | — | Default actor IDs used by the trends helpers |

**Example prompts:**
- *"What's trending on Google for 'AI' in the US over the last month, and pull related queries."*
- *"Aggregate posts about #climate across Instagram, TikTok, and Reddit and rank by engagement."*
- *"Run the apify/google-trends-scraper for 'space exploration', 'mars', 'starship' worldwide for the last 12 months."*
- *"Find recent TikTok videos tagged #fintech and Reddit posts about 'fintech' from r/technology."*

---

### AppSheet (`apps/appsheet/mcp.py`)

Wraps the AppSheet [API v2](https://support.google.com/appsheet/answer/10105768) — find/add/edit/delete rows in any table of an AppSheet app. Auth is the per-app `ApplicationAccessKey` header (generated in *Manage → Integrations*). Requires valid `APPSHEET` section in `apps_config.yaml`.

| Tool | Args | Returns |
|------|------|---------|
| `appsheet_find_rows` | `table`, `selector?`, `app_id?` | List of row dicts (full column set returned by the app) |
| `appsheet_add_rows` | `table`, `rows`, `app_id?` | List of inserted row dicts (with system columns filled in) |
| `appsheet_edit_rows` | `table`, `rows`, `app_id?` | List of updated row dicts — each row must include the key column |
| `appsheet_delete_rows` | `table`, `rows`, `app_id?` | `{deleted, raw}` |

`selector` is an AppSheet expression evaluated server-side, e.g. `Filter("Tasks", [Status] = "Open")`. `app_id` falls back to `APPSHEET.default_app_id` when omitted.

**Example prompts:**
- *"Show every open task in my AppSheet 'Tasks' table."*
- *"Find rows in 'Inventory' where Qty is greater than 0."*
- *"Add a row to 'Leads' with Name 'Acme' and Email 'hi@acme.com'."*

---

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

### Stripe (`apps/stripe/mcp.py`)

Wraps the Stripe [REST API v1](https://docs.stripe.com/api) — balance, charges, customers, invoices, payment intents, subscriptions, and the events audit trail. Auth is the secret key (`sk_live_…` / `sk_test_…`) sent as a Bearer token. Requires valid `STRIPE` section in `apps_config.yaml`.

| Tool | Args | Returns |
|------|------|---------|
| `stripe_get_balance` | — | Account balance — `available`, `pending`, `instant_available` per currency |
| `stripe_list_balance_transactions` | `limit?`, `type_filter?` | Ledger entries (charges, refunds, payouts, fees) |
| `stripe_list_charges` | `limit?`, `customer?` | Recent charges, newest first |
| `stripe_get_charge` | `charge_id` | Single charge by id |
| `stripe_list_customers` | `limit?`, `email?` | Customers (filter by exact-match email) |
| `stripe_get_customer` | `customer_id` | Single customer |
| `stripe_search_customers` | `query`, `limit?` | Stripe-search-language results — `email:'a@b.com'`, `metadata['k']:'v'` |
| `stripe_create_customer` | `email?`, `name?`, `description?`, `phone?` | New customer object |
| `stripe_list_invoices` | `limit?`, `customer?`, `status?` | Invoices filterable by status (`draft`, `open`, `paid`, `void`) |
| `stripe_get_invoice` | `invoice_id` | Single invoice |
| `stripe_get_upcoming_invoice` | `customer` | Preview of next invoice for a customer |
| `stripe_list_payment_intents` | `limit?`, `customer?` | PaymentIntents (modern payment lifecycle) |
| `stripe_get_payment_intent` | `intent_id` | Single PaymentIntent |
| `stripe_list_subscriptions` | `limit?`, `customer?`, `status?` | Subscriptions (status: `active`, `past_due`, `canceled`, `trialing`, `all`) |
| `stripe_get_subscription` | `subscription_id` | Single subscription |
| `stripe_list_events` | `limit?`, `type_filter?` | Audit trail / webhook history — filter by event type |
| `stripe_get_event` | `event_id` | Single event |

Amounts are in the smallest currency unit (cents for USD). Pagination is cursor-based via `starting_after`. The base service overrides `Content-Type` to `application/x-www-form-urlencoded` because Stripe doesn't accept JSON bodies.

**Example prompts:**
- *"What's my Stripe balance right now?"*
- *"Show me the last 20 charges and total them."*
- *"List all open invoices for customer cus_ABC123."*
- *"Find the customer whose email is brian@example.com and list their subscriptions."*
- *"Pull the last 50 `charge.failed` events to investigate failures."*

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

### Restricting the app surface per node (`MCP_ENABLED_APPS`)

By default every app in `APP_REGISTRARS` is registered. For node-specific deployments
(e.g. a worker that should only expose Trello + Discord) set the comma-separated env var
`MCP_ENABLED_APPS` to the case-insensitive labels you want to keep:

```sh
# Only register Trello and Discord, even though many apps are wired up
export MCP_ENABLED_APPS="trello,discord"
python mcp/server.py
```

Labels match the first column of `APP_REGISTRARS` in `mcp/server.py` ("Trello", "Discord",
"Knowledge / RAG", etc.). Whitespace is trimmed; matching is case-insensitive. Unset or empty
preserves the legacy "register everything" behavior.

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
