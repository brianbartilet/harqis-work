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

The canonical app registry now lives in `tools/catalog.py`. The standalone server,
Kanban bridge, and low-context CLI consume that one registry, preventing registration drift.
Coding agents with shell access should prefer `python -m tools`; MCP remains available
for typed tool clients and existing integrations.

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
├── telegram/mcp.py                   # Telegram bot tools
└── youtube/mcp.py                    # YouTube channel and analytics tools
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

### File Index (`apps/file_index/mcp.py`)

Local catalog tools; run on the catalog host with its `FILES_STORE_PATH`.

| Tool | Description |
|---|---|
| `search_file_index_files` | Paginated name/tag/category metadata search |
| `get_file_index_file` | File metadata and storage locations |
| `list_file_index_sources` | Configured source roots and last scan status |
| `get_file_index_package` | Owner-visible revisions and audit |
| `create_file_index_output` | **Write** generated-output metadata under an enabled local source; does not share content |

*Find indexed files tagged research.*
*Inspect the locations of this file.*
*Register this generated report in the file catalog.*

Publication remains an explicit owner UI command. See
[File Index](../apps/file_index/README.md) and its deployment guide.

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

### Granola (`apps/granola/mcp.py`)

Read-only official API tools; requires `GRANOLA_API_KEY`. These do not write HFL.

| Tool | Args | Returns |
| --- | --- | --- |
| `list_granola_notes` | `created_after?`, `created_before?`, `updated_after?`, `folder_id?`, `cursor?`, `page_size?` | One metadata page |
| `get_granola_note` | `note_id`, `include_transcript?` | Full note, including accessible private notes |
| `get_granola_transcript` | `note_id`, `cursor?`, `page_size?` | One transcript page |
| `list_granola_folders` | `cursor?`, `page_size?` | One folder page |

The Memory tool `granola_activity(period?, since?, until?, folder_id?,
max_notes?, cursor?, synthesize?)` previews selected summaries without corpus
writes. `synthesize` defaults false. Empty windows make no model call.

*“List my Granola folders so I can choose an HFL import folder.”*
*“Preview this week's Granola meeting summaries without saving them.”*

See [configuration and boundaries](../apps/granola/README.md).

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

### HFL Activity Corpus (`apps/hfl_corpus/mcp.py`)

121 typed tools cover the canonical frontend `/api/hfl` routes using
`HFL_CORPUS_API_URL` and `HFL_CORPUS_API_TOKEN`. The same catalog powers the CLI
and agent bridge. Existing tool names are retained. See the
[app guide](../apps/hfl_corpus/README.md) for version checks, merge preview tokens,
file transfer, scheduling boundaries and discovery commands, and the
[frontend coverage report](../docs/info/FRONTEND_MCP_COVERAGE.md) for remaining
session/protocol surfaces. Writes are marked below; file downloads write locally.

| Tool | Description |
| --- | --- |
| `upload_hfl_corpus_attachments` | Attach multiple supporting files to an action or pin (remote write). |
| `create_hfl_corpus_entity_consolidation` | Begin or resume an entity consolidation run. Destructive: writes remote state. |
| `get_hfl_corpus_entity_consolidation` | Read a consolidation run and its candidate decisions. |
| `update_hfl_corpus_entity_consolidation_decision` | Record a decision and apply an eligible merge. Destructive: writes remote state. |
| `update_hfl_corpus_entity_consolidation_decisions` | Submit up to 20 pair decisions; results report each success or error. Destructive: writes remote state. |
| `update_hfl_corpus_entity_consolidation_finish` | Finish a decided run and dispatch its reports. Destructive: writes remote state. |
| `create_hfl_corpus_entity_consolidation_claim` | Claim a disjoint anchor packet. Destructive: writes remote state. |
| `update_hfl_corpus_entity_consolidation_claim` | Renew or release a review lease. Destructive: writes remote state. |
| `update_hfl_corpus_entity_consolidation_checkpoint` | Checkpoint partial progress and discover changed inputs. Destructive: writes remote state. |
| `update_hfl_corpus_entity_consolidation_evidence` | Cache bounded original-entry context across pending pairs. Destructive: writes remote state. |
| `create_hfl_corpus_entity_consolidation_group` | Commit independently corroborated anchor pairs atomically. Destructive: writes remote state. |
| `get_hfl_corpus_role_history` | Read private facet revision history. |
| `list_hfl_corpus_item_connection_options` | Search visible ideas/actions available for manual linking, with query and offset pagination. |
| `update_hfl_corpus_item_connection` | Create, update or remove a shared manual link; update/remove require the current revision (destructive remote write). |
| `get_hfl_corpus_board_context` | Read active boards and permitted member objects and connections. |
| `get_hfl_corpus_idea_connections` | Read an idea's graph connections. |
| `list_hfl_corpus_reuse_options` | Search actions and ideas available for independent copying. |
| `list_hfl_corpus_board_ideas` | List ideas available to boards, optionally including dismissed ideas. |
| `get_hfl_corpus_clone_draft` | Preview an independent action or idea copy without saving it. |
| `create_hfl_corpus_clone` | Create a copy using a caller UUID and source revision (remote write). |
| `create_hfl_corpus_list_copy` | Copy a checklist into an action or idea at the expected revision (remote write). |
| `create_hfl_corpus_map_paste` | Paste selected objects between versioned boards (remote write). |
| `get_hfl_corpus_list` | Read a standalone or owner-linked checklist entity. |
| `create_hfl_corpus_list` | Create a standalone checklist with a caller UUID (remote write). |
| `update_hfl_corpus_list` | Update a checklist at its expected revision (remote write). |
| `list_hfl_corpus_attachments` | List supporting files attached to a task. |
| `download_hfl_corpus_attachment` | Download an input attachment (writes a local file). |
| `delete_hfl_corpus_attachment` | Detach an input from future runs (remote write). Prior run files are retained. |
| `create_hfl_corpus_action` | Create an action (writes remote state), with scheduled agent execution disabled. |
| `list_hfl_corpus_actions` | List actions, up to 500 per page. |
| `get_hfl_corpus_action` | Read an action and its current version. |
| `update_hfl_corpus_action` | Edit, complete, or dismiss an action (writes remote state). |
| `get_hfl_corpus_action_history` | Read immutable action revisions. |
| `create_hfl_corpus_category` | Create a Memory Signal category (writes remote state). |
| `list_hfl_corpus_categories` | List active and archived Memory Signal categories and the color palette. |
| `get_hfl_corpus_category` | Read a Memory Signal category, including an archived category. |
| `update_hfl_corpus_category` | Edit a category (writes remote state). |
| `archive_hfl_corpus_category` | Archive a category and hide its pins, retaining history (writes remote state). |
| `create_hfl_corpus_pin` | Pin dates (writes remote state). A prompt does not enable agent execution. |
| `list_hfl_corpus_pins` | List date pins in active categories. |
| `get_hfl_corpus_pin` | Read a date pin in an active category. |
| `update_hfl_corpus_pin` | Edit a date pin (writes remote state); preserves its agent setting. |
| `delete_hfl_corpus_pin` | Delete a date pin (destructive remote write). |
| `create_hfl_corpus_entry` | Create a durable HFL entry. This writes Markdown and attempts an ES upsert. |
| `preview_hfl_corpus_entry` | Preview a rendered HFL entry without saving it. |
| `upload_hfl_corpus_entry` | Create a durable HFL entry and upload attachments. This writes remote state. |
| `list_hfl_corpus_documents` | Search and paginate canonical HFL documents. |
| `get_hfl_corpus_tree` | Get a shallow directory tree from the canonical corpus. |
| `list_hfl_corpus_matches` | List matching entries within one HFL Markdown document. |
| `get_hfl_corpus_document` | Get one HFL document with parsed entries and safe references. |
| `update_hfl_corpus_document` | Replace an HFL document. Destructive: overwrites canonical Markdown text. |
| `update_hfl_corpus_entry` | Update one entry with its anchor and last-read revision, optionally uploading attachments (destructive remote write). |
| `get_hfl_corpus_reference_preview` | Get a safe HTML preview for a text or Markdown reference. |
| `download_hfl_corpus_reference` | Download a reference to a local path. This writes a local file. |
| `download_hfl_corpus_reference_media` | Download reference image/video content. This writes a local file. |
| `download_hfl_corpus_reference_thumbnail` | Download a reference thumbnail. This writes a local file. |
| `list_hfl_corpus_entities` | Search the entity directory with explicit pagination (limit 1–10000). |
| `get_hfl_corpus_entity_graph` | Read the entity graph; limit is 0–1000, with 0 requesting all nodes. |
| `get_hfl_corpus_entity_entry` | Read an entity-linked entry preview and its safe references. |
| `get_hfl_corpus_entity_status` | Read entity enrichment state and legacy merge decisions. |
| `update_hfl_corpus_entity_profile` | Replace entity profile fields; omitted lists are cleared. Destructive: writes remote state. |
| `create_hfl_corpus_entity_backfill` | Request entity enrichment/backfill on the canonical host. Destructive: writes remote state. |
| `create_hfl_corpus_entity_legacy_merge` | Legacy pair merge; prefer the preview-token bulk merge flow. Destructive: writes remote state. |
| `update_hfl_corpus_entity_legacy_undo` | Undo a legacy pair-merge decision. Destructive: writes remote state. |
| `create_hfl_corpus_entity_export` | Write the canonical host’s configured Obsidian export; requires HARQIS_OBSIDIAN_VAULT. Destructive: writes remote state. |
| `analyze_hfl_corpus_entity_selection` | Preview a same-type entity merge and obtain a short-lived preview token. Read-only. |
| `create_hfl_corpus_entity_merge` | Commit a reviewed entity merge; reuse the UUID and identical payload on retry. Destructive: writes remote state. |
| `update_hfl_corpus_entity_unmerge` | Reverse a bulk merge, preserving audit history; UUID is required for idempotency. Destructive: writes remote state. |
| `get_hfl_corpus_entity_operation` | Read a committed merge/unmerge result and audit delivery state. |
| `get_hfl_corpus_entity_audit` | Read immutable entity merge/unmerge audit events. |
| `get_hfl_corpus_entity_matching` | Read matching scan status and candidate suggestions. |
| `create_hfl_corpus_entity_matching_scan` | Request a matching scan; this may schedule background work. Destructive: writes remote state. |
| `update_hfl_corpus_entity_matching_dismiss` | Dismiss a matching suggestion. Destructive: writes remote state. |
| `list_hfl_corpus_graph_views` | List saved graph views and the selected view. |
| `create_hfl_corpus_graph_view` | Create and select a named graph view. Destructive: writes remote state. |
| `update_hfl_corpus_graph_view` | Replace a saved graph view using its latest revision. Destructive: writes remote state. |
| `update_hfl_corpus_graph_view_selection` | Select an existing saved graph view. Destructive: writes remote state. |
| `delete_hfl_corpus_graph_view` | Delete a graph view with an optimistic revision check. Destructive: writes remote state. |
| `get_hfl_corpus_timeline_source` | Validate and read the title/date of unprotected entry evidence. |
| `get_hfl_corpus_timeline_evidence` | Return the validated evidence navigation link without following its redirect. |
| `list_hfl_corpus_timeline_items` | List up to 500 scoped agenda items with board positions and due-state grouping. |
| `update_hfl_corpus_timeline_order` | Reorder a status column with item version checks. Destructive: writes remote state. |
| `create_hfl_corpus_timeline_item` | Create/adopt an agenda item. May configure agent execution if explicitly requested. Destructive: writes remote state. |
| `create_hfl_corpus_checklist_action` | Create an action and tick the source checklist item atomically, with version checks and retry-safe creation. Agent execution stays disabled. Destructive: writes remote state. |
| `update_hfl_corpus_timeline_item` | Update an agenda item using its latest version. Can alter scheduling; completion writes a receipt. Destructive: writes remote state. |
| `get_hfl_corpus_timeline_item` | Read the current agenda item and version. |
| `get_hfl_corpus_timeline_history` | Read immutable agenda revisions and rendered completion notes. |
| `get_hfl_corpus_timeline_markers` | Read scoped action date markers and aggregate statuses. |
| `get_hfl_corpus_timeline_period` | Read agenda items, suggestions, receipts and exploration state for 1–31 inclusive days. |
| `update_hfl_corpus_timeline_suggestion_dismiss` | Dismiss an idea/suggestion. Destructive: writes remote state. |
| `create_hfl_corpus_timeline_exploration` | Schedule AI exploration for 1–31 days ending today or earlier; may incur model usage. Destructive: writes remote state. |
| `get_hfl_corpus_ideas_snapshot` | Read ideas, maps, links, goals and visible graph context. |
| `get_hfl_corpus_connection_availability` | Read available object connection choices. |
| `get_hfl_corpus_action_connections` | Read an action’s graph connections. |
| `get_hfl_corpus_date_connections` | Read a date pin’s graph connections. |
| `list_hfl_corpus_boards` | Read board metadata, goals and the color palette without scanning the corpus. |
| `update_hfl_corpus_board_order` | Persist board ordering. Destructive: writes remote state. |
| `update_hfl_corpus_goal_order` | Persist goal ordering. Destructive: writes remote state. |
| `get_hfl_corpus_goal_options` | List visible ideas/actions that can be linked to goals. |
| `get_hfl_corpus_map` | Read a mind map and current version. |
| `get_hfl_corpus_map_graph` | Read the visible graph projection for map members. |
| `list_hfl_corpus_map_attach_options` | Search attachable objects; returns 50 per page. |
| `get_hfl_corpus_rendered_markdown` | Render up to 60000 characters of Markdown using the frontend renderer. Read-only. |
| `get_hfl_corpus_idea` | Read an idea, version and rendered content. |
| `create_hfl_corpus_idea` | Create an idea; reuse the request UUID for stable identity. Destructive: writes remote state. |
| `update_hfl_corpus_idea` | Edit/dismiss/restore an idea using the latest version. Destructive: writes remote state. |
| `create_hfl_corpus_topic` | Create a named graph topic and initial entity profile; URLs are not topic names. Destructive: writes remote state. |
| `create_hfl_corpus_link` | Create a durable relation between visible graph nodes. Destructive: writes remote state. |
| `delete_hfl_corpus_link` | Delete a durable relation between visible graph nodes. Destructive: writes remote state. |
| `create_hfl_corpus_map` | Create a versioned mind map; UUID determines its stable identity. Destructive: writes remote state. |
| `update_hfl_corpus_map` | Update map membership/content/layout with an optimistic version check. Destructive: writes remote state. |
| `delete_hfl_corpus_map` | Delete a map using its latest version; shared objects remain independently owned. Destructive: writes remote state. |
| `create_hfl_corpus_map_promotion` | Promote a map draft into a durable idea. Destructive: writes remote state. |
| `get_hfl_corpus_goal` | Read a goal with its current version. |
| `create_hfl_corpus_map_link_promotion` | Promote a map connection to a durable graph relation. Destructive: writes remote state. |
| `update_hfl_corpus_map_connection` | Edit a board connection using its current board/edge revision. Destructive: writes remote state. |
| `create_hfl_corpus_goal` | Create a durable goal with validated idea/action links. Destructive: writes remote state. |
| `update_hfl_corpus_goal` | Update a goal with optimistic concurrency and validated milestone links. Destructive: writes remote state. |
| `get_hfl_corpus_idea_conversion` | Preview conversion of an idea or checklist item into an action. |
| `create_hfl_corpus_idea_conversion` | Convert an idea to an action, clone selected attachments, and mark it adopted. Agent execution remains disabled. Destructive: writes remote state. |
| `list_hfl_corpus_idea_attachments` | List an idea’s supporting files. |
| `download_hfl_corpus_idea_attachment` | Download a supporting file to a local path; replaces an existing destination. Destructive: writes a local file. |
| `upload_hfl_corpus_idea_attachments` | Attach supporting files to an idea; at most 50 files of 500 MB each. Destructive: writes remote state. |
| `delete_hfl_corpus_idea_attachment` | Detach a supporting file from an idea. Destructive: writes remote state. |
| `create_hfl_corpus_map_proposal` | Accept a proposed thought into a map with at most five existing parents. Destructive: writes remote state. |
| `list_hfl_corpus_day_matches` | Read matching entries across documents for one YYYY-MM-DD activity date; maximum 20 per page. |

*"Find the entities matching this name and preview a same-type merge."*

*"Create a mind map for this project and attach the supporting notes to its idea."*

*"Show my agenda for this week, including version numbers before I edit it."*

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

### Plaud (`apps/plaud/mcp.py`)

Wraps the Plaud AI voice recorder. Tries the (unofficial) cloud API first and falls back to a local export folder. [Dev API](https://docs.plaud.ai/). Requires a valid `PLAUD` section in `apps_config.yaml` (`PLAUD_TOKEN` and/or `PLAUD_EXPORT_DIR`).

| Tool | Args | Returns |
|------|------|---------|
| `list_plaud_recordings` | `since?`, `until?` (ISO-8601) | Recordings in the window: `{id, title, started_at, duration_seconds, audio_format, has_transcript, has_summary, origin}` |
| `get_plaud_transcript` | `recording_id` | `{id, transcript, summary}` (empty if Plaud has not produced them) |
| `plaud_status` | — | `{cloud_ready, folder_ready, active}` |

**Example prompts:**
- *"List my Plaud recordings from yesterday."*
- *"Is the Plaud cloud connection working or are we on the export folder?"*

---

### Google Apps (`apps/google_apps/mcp.py`)

Wraps `apps/google_apps/references/web/api/` services.

Config sections required in `apps_config.yaml`:
- `GOOGLE_APPS` — Calendar (uses `credentials.json` / `storage.json`)
- `GOOGLE_KEEP` — Keep notes (uses `credentials-ha.json` / `storage-ha.json`)
- `GOOGLE_GMAIL` — Gmail (uses `credentials.json` / `storage-gmail.json`)
- `GOOGLE_GMAIL_SEND` — Gmail sending (uses `credentials.json` / `storage-gmail-send.json`)

| Tool | Args | Returns |
|------|------|---------|
| `get_google_calendar_events_today` | `event_type?` | Today's calendar events (ALL/ALL_DAY/NOW/SCHEDULED/UPCOMING_UNTIL_EOD) |
| `get_google_calendar_holidays` | `country_code?` | Public holidays for a country |
| `list_google_keep_notes` | `filter?` | List Keep notes (non-trashed by default) |
| `get_google_keep_note` | `name` | Get a specific Keep note by resource name |
| `create_google_keep_note` | `title`, `text` | Create a new Keep note |
| `get_gmail_recent_emails` | `max_results?`, `query?` | Recent emails with subject, sender, date, snippet, body |
| `search_gmail` | `query`, `max_results?` | Search Gmail using Gmail search syntax |
| `send_gmail_email` | `to`, `subject`, `body`, `operation_key`, `attachments?`, `body_html?` | Send an authorized message and host-file attachments; stable keys protect against duplicate retries |

**Gmail OAuth note:** On first use, the Gmail tool will open a browser to complete the OAuth consent
flow and write the token to `storage-gmail.json`. Subsequent calls use the cached token silently.

Sending uses `GOOGLE_GMAIL_SEND` with its `gmail.send` grant, matching the test farm
email workflow. Reading and searching use `GOOGLE_GMAIL` with `gmail.readonly`.
Both credentials must be authorized for the intended account on the MCP host.
Attachments must exist on that host (30 files / 20 MB total). Keep the send receipt
ledger durable and reconcile uncertain outcomes before another send. See the
[Gmail service reference](../apps/google_apps/README.md#gmail-sending-and-attachments)
and [Activity Corpus operations guide](../docs/info/HFL-AGENT-BRIDGE.md).

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

### Spotify (`apps/spotify/mcp.py`)

Wraps `apps/spotify/references/web/api/` services. Requires valid `SPOTIFY` section in `apps_config.yaml` (OAuth2 refresh-token flow). Read-only personal listening signal.

| Tool | Args | Returns |
|------|------|---------|
| `spotify_recently_played` | `limit?` | Last ≤50 plays, newest first, each with `played_at` + `track` |
| `spotify_currently_playing` | — | Track playing now, or `{}` if nothing is |
| `spotify_top_tracks` | `time_range?`, `limit?` | Top tracks over short/medium/long_term |
| `spotify_top_artists` | `time_range?`, `limit?` | Top artists over short/medium/long_term |

**Example prompts:**
- *"What have I listened to on Spotify recently?"*
- *"What are my top artists this month?"*

---

### JustTCG (`apps/justtcg/mcp.py`)

Wraps `apps/justtcg/references/web/api/` services. Requires valid `JUSTTCG` section in `apps_config.yaml`.
Multi-game TCG pricing analytics (MTG, Pokémon, Yu-Gi-Oh!, Lorcana, One Piece, Digimon, Union Arena).

| Tool | Args | Returns |
|------|------|---------|
| `list_justtcg_games` | — | Supported games + aggregate value stats |
| `list_justtcg_sets` | `game?`, `q?`, `limit?`, `offset?` | Sets within a game (filter by game id / name) |
| `get_justtcg_card` | `card_id?`, `variant_id?`, `tcgplayer_id?`, `condition?`, `printing?` | One card + its priced variants |
| `search_justtcg_cards` | `q?`, `game?`, `set_id?`, `condition?`, `printing?`, `order_by?`, `order?`, `limit?`, `offset?` | Search/browse; sort by `order_by` (`price`/`24h`/`7d`/`30d`) |
| `batch_justtcg_cards` | `items` | Batch lookup (plan cap 20/100/200) |

Pricing lives per-variant: `price`, `priceChange24hr`/`7d`/`30d`, `avgPrice`, `minPrice7d`/`maxPrice7d`,
`trendSlope7d`, `priceRelativeTo30dRange`, `minPriceAllTime`, etc.

**Example prompts:**
- *"What are the biggest 7-day Pokémon card price movers on JustTCG?"*
- *"Get the current JustTCG price for the card with TCGplayer id 106999."*
- *"Look up Charizard in the Base Set Shadowless set and show the Near Mint Holofoil price."*

---

### Pokemon TCG (`apps/pokemon_tcg/mcp.py`)

Wraps `apps/pokemon_tcg/references/web/api/` services ([API docs](https://docs.pokemontcg.io)).
Requires valid `POKEMON_TCG` section in `apps_config.yaml` (the API key is optional — keyless
access works at lower rate limits).

| Tool | Args | Returns |
|------|------|---------|
| `search_pokemon_tcg_cards` | `q`, `page?`, `page_size?`, `order_by?`, `select?` | Cards matching a Lucene-style query |
| `get_pokemon_tcg_cards_by_dex` | `dex_number`, `rarity?` | A Pokemon's printings by National Dex number, newest set first |
| `list_pokemon_tcg_sets` | `q?`, `order_by?` | Expansion sets (newest first by default) |
| `list_pokemon_tcg_rarities` | — | Every exact rarity string (no literal "Full Art" exists) |

**Example prompts:**
- *"Which sets contain a Charizard Special Illustration Rare?"*
- *"List every Pokemon TCG rarity string."*
- *"Show Pikachu's Illustration Rare printings, newest first."*

---

### MPC (`apps/mpc/mcp.py`)

Order-file tooling for the [MakePlayingCards.com autofill driver](../apps/mpc/README.md)
(Playwright port of [mpc-autofill](https://github.com/chilli-axe/mpc-autofill)). Requires valid
`MPC` section in `apps_config.yaml`. The browser driver itself is not exposed over MCP — run it
via `workflows/tcg` or pytest.

| Tool | Args | Returns |
|------|------|---------|
| `build_mpc_order_xml` | `fronts_dir`, `cardback_path`, `output_path`, `stock?`, `name_prefix?` | Order XML path(s), auto-split at 612 cards, with validation problems |
| `validate_mpc_order` | `xml_path` | Order summary + problem list (slot coverage, missing files, caps) |

**Example prompts:**
- *"Build an MPC order XML from the rendered cards in workflows/tcg/output/cards."*
- *"Validate the order file pokedex_proxies_1.xml."*

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

### YouTube (`apps/youtube/mcp.py`)

Wraps the YouTube Data API v3 and YouTube Analytics API v2. Requires the `YOUTUBE` config section, enabled APIs, and an OAuth token in `.env/storage-youtube.json`.

| Tool | Args | Returns |
|------|------|---------|
| `get_youtube_my_channel` | — | Authenticated channel metadata and statistics |
| `get_youtube_channel` | `channel_id` | Channel metadata and statistics |
| `list_youtube_playlists` | `channel_id?`, `max_results?` | Channel playlists |
| `list_youtube_playlist_videos` | `playlist_id`, `max_results?` | Unique playlist videos; omit the limit to auto-paginate all |
| `list_youtube_channel_videos` | `channel_id?`, `max_results?` | Unique channel uploads; omit the limit to auto-paginate all |
| `get_youtube_video` | `video_id` | Video metadata and statistics |
| `search_youtube_videos` | `query`, `channel_id?`, `max_results?` | Public video search results |
| `analyze_youtube_channel` | dates, metrics, optional dimensions/filters/sort | Targeted Analytics report |
| `get_youtube_channel_summary` | `start_date`, `end_date` | Headline Studio metrics |
| `get_youtube_top_videos` | `start_date`, `end_date`, `max_results?` | Top videos by views |

**Example prompts:**
- *"List all videos uploaded to my YouTube channel."*
- *"Show my YouTube channel summary for the last 30 days."*
- *"Which videos had the most views this quarter?"*

---

## Running the server

```sh
# From repo root, activate your venv first
python mcp/server.py
```

The server starts in `stdio` mode (the default for local Claude Desktop connections). You will see
startup logs confirming which tools were registered.

### Low-context CLI alternative

The CLI loads no app schemas during discovery and imports only the selected app when commands,
schemas, or calls are requested:

```sh
python -m tools apps
python -m tools commands ynab
python -m tools schema trello create_trello_card
python -m tools call scryfall get_scryfall_card_prices --input '{"identifier":"Black Lotus"}'
```

Write operations require `--confirm-write`. See `tools/README.md` for JSON envelopes,
profile authorization, and audit behavior.

### Restricting the app surface per node (`MCP_ENABLED_APPS`)

`[harqis-server.env_vars]` in `machines.toml` includes `hfl_corpus` alongside
`memory` (recall) and the host's other integrations. `machines.local.toml` can
override this list; its value must also include `hfl_corpus` when deploying the
canonical frontend tools. Direct `mcp/server.py` and `scripts/launch.py mcp`
launches both load `apps.env` followed by machine-specific URLs and credentials
before importing app configuration. An explicitly supplied client
`MCP_ENABLED_APPS` filter takes precedence over the machine default.

### Remote operations on the canonical instance

There are two supported connection paths:

1. Run MCP locally with `HFL_CORPUS_API_URL` pointing to the canonical frontend
   or standalone HFL API and `HFL_CORPUS_API_TOKEN` available in private host
   configuration. Tool requests, including authorized writes, go to that API.
   Upload source files and download destinations are local to the MCP process.
2. Run MCP on the server over SSH stdio. The SSH user needs access to the
   checkout and its virtual environment; API credentials stay on the server.
   Files referenced by tools are then paths on the server.

Example generic MCP client configuration (replace the SSH destination and
checkout path with your configured host):

```json
{
  "mcpServers": {
    "harqis-server-hfl": {
      "command": "ssh",
      "args": [
        "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
        "user@harqis-server",
        "cd /absolute/path/to/harqis-work && MCP_ENABLED_APPS=hfl_corpus .venv/bin/python mcp/server.py"
      ]
    }
  }
}
```

This uses the existing SSH connection and stdio protocol; there is no MCP HTTP
listener to deploy. The client must retain the environment needed by its SSH
authentication (for example `SSH_AUTH_SOCK` when using an agent). First verify `tools/list` and a read such as
`list_hfl_corpus_categories`. After deploying the expanded adapter, expect 100
HFL tools. Reconnect existing clients after code or environment changes: a
running MCP process retains its loaded configuration and registered tool list.

### Per-client app filtering

Without an app filter every app in the shared `APP_CATALOG` is registered. Machine configuration
may supply a default filter, as `harqis-server` does. For node-specific deployments
(e.g. a worker that should only expose Trello + Discord) set the comma-separated env var
`MCP_ENABLED_APPS` to the case-insensitive labels you want to keep:

```sh
# Only register Trello and Discord, even though many apps are wired up
export MCP_ENABLED_APPS="trello,discord"
python mcp/server.py
```

Values may use the catalog key or label (`trello`, `Discord`, `Knowledge / RAG`, etc.).
Whitespace is trimmed; matching is case-insensitive. An explicitly empty value registers
everything; an unset value uses the machine default, or everything if no default exists.

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

**Use the `/create-new-mcp` skill** — it is the single source of truth for the MCP layer. Run
`/create-new-mcp <app_name>` and it will audit the app's service methods, generate the wrappers,
and wire registration + docs for you. If the app doesn't exist yet, it loops back to
`/create-new-service-app` first. (That scaffolding skill, in turn, delegates its MCP step to
`/create-new-mcp`.)

What the skill does — and what to do if wiring it by hand:

1. Create `apps/<app_name>/mcp.py` with a single `register_<app_name>_tools(mcp)` function. Each
   tool needs a docstring (`Args:` section), entry/result `logger.info` calls, and a defensive
   return serialization (DTOs via `.__dict__`, never a raw DTO/Response):

```python
import logging
from mcp.server.fastmcp import FastMCP
from apps.<app_name>.config import CONFIG
from apps.<app_name>.references.web.api.<service> import ApiService<App>

logger = logging.getLogger("harqis-mcp.<app_name>")

def register_<app_name>_tools(mcp: FastMCP):

    @mcp.tool()
    def my_tool(param: str) -> dict:
        """Describe what Claude should know about this tool.

        Args:
            param: what it is.
        """
        logger.info("Tool called: my_tool param=%s", param)
        service = ApiService<App>(CONFIG)
        result = service.some_method(param)
        return result if isinstance(result, dict) else (result.__dict__ if hasattr(result, "__dict__") else {})
```

2. Register once in `tools/catalog.py` by adding an `AppToolSpec`. This exposes the app
   to the CLI, standalone MCP server, and Kanban bridge:

```python
    AppToolSpec("<app_name>", "<Label>", "apps.<app_name>.mcp.register_<app_name>_tools"),
```

If you only added tools to an app that's already registered, the catalog needs no change — all
three surfaces pick up the new tools automatically.

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


### Unified entity Soul tools

| Tool | Purpose |
|---|---|
| `get_hfl_corpus_entity_soul_editor` | Read profile, identity, connections and concurrency revision. |
| `update_hfl_corpus_entity_soul_editor` | Atomically save all three sections (destructive remote write). |

*Show the Soul details for this entity.*
*Update the entity profile and connections together using its current revision.*

The save payload follows the canonical SoulEditorWrite schema; conflicts leave all
sections unchanged. Existing entity context and soul tools remain available.

### Entity reliability tools

| Tool | Purpose |
| --- | --- |
| `search_hfl_corpus_entity_duplicates` | Suggest existing identities before manual creation. |
| `get_hfl_corpus_entity_resolution_health` | Read resolver throughput, pending age, failures and outcomes. |
| `update_hfl_corpus_entity_resolution_retry` | Requeue one investigated failed resolver job. **Destructive: remote write.** |
| `update_hfl_corpus_entity_integrity` | Set or clear an audited identity-review flag. **Destructive: remote write.** |
| `update_hfl_corpus_entity_separation_reverse` | Reverse a consolidation separation while preserving unmerge vetoes. **Destructive: remote write.** |
| `create_hfl_corpus_entity_consolidation_execution` | Start or recover a bounded consolidation execution. **Destructive: remote write.** |
| `update_hfl_corpus_entity_consolidation_execution_close` | Close a bounded execution and dispatch its canonical report. **Destructive: remote write.** |

Creation may return `possible-existing`; reuse a suggestion or explicitly set `confirm_distinct` on `create_hfl_corpus_entity`. Reuse execution IDs and exact close payloads after transport failures.

*"Show incoming entity-resolution health."*

*"Finish a bounded entity-consolidation execution and verify its report."*
