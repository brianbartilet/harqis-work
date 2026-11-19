# Integration reference

[Overview](../../README.md) · [Documentation index](README.md)

## App Inventory

| App | Integration | Type | Tests | Links |
|-----|-------------|------|-------|-------|
| `aaa` | Philippine stock exchange (PSEI) | Selenium | Yes | [Site](https://aaa-equities.com.ph/) |
| `airtable` | Airtable bases, tables, fields, and full record CRUD with formula filters and upsert | REST API | Yes | [API Docs](https://airtable.com/developers/web/api/introduction) · [Site](https://airtable.com/) |
| `alpha_vantage` | Stock quotes, FX rates, news & sentiment, fundamentals, technical indicators, crypto, commodities, economic indicators | REST API | Yes | [API Docs](https://www.alphavantage.co/documentation/) · [MCP](https://mcp.alphavantage.co/) · [Site](https://www.alphavantage.co/) |
| `android_emulator` | Android emulators (AVDs) and physical/wireless devices — ADB shell, install APKs, snapshots, scrcpy screen mirroring | Local | Yes | — |
| `antropic` | Anthropic Claude API | REST (native SDK) | Yes | [API Docs](https://docs.anthropic.com/en/api/) · [Console](https://console.anthropic.com/) |
| `apify` | Web scraping platform — run actors, fetch datasets, social-media trends aggregation (Google Trends, IG, FB, TikTok, Reddit) | REST API | Yes | [API Docs](https://docs.apify.com/api/v2) · [Store](https://apify.com/store) · [Console](https://console.apify.com/) |
| `appsheet` | AppSheet tables — find/add/edit/delete rows via the v2 REST API | REST API | Yes | [API Docs](https://support.google.com/appsheet/answer/10105768) · [Site](https://www.appsheet.com/) |
| `browser` | HTTP fetching and web scraping (httpx + BeautifulSoup) | Local | No | — |
| `confluence` | Confluence pages, spaces, full-text search (Cloud and Server / DC) | REST API | Yes | [API Docs](https://developer.atlassian.com/cloud/confluence/rest/) · [Site](https://www.atlassian.com/software/confluence) |
| `desktop` | Windows desktop automation | Local | Yes | — |
| `discord` | Discord bot — messaging, guilds, webhooks | REST API | Yes | [API Docs](https://discord.com/developers/docs/reference) · [Portal](https://discord.com/developers/applications) |
| `echo_mtg` | MTG collection management | REST API | Yes | [API Docs](https://www.echomtg.com/api/) · [Site](https://www.echomtg.com/) |
| `file_index` | Metadata file catalog, multi-source discovery, revisioned Drive packages and expiry | Local + provider adapters | Yes | [Deployment](FILES-DEPLOYMENT.md) |
| `filesystem` | Local file and directory operations (pathlib) | Local | No | — |
| `gemini` | Google Gemini — text generation, token counting, embeddings | REST API | Yes | [API Docs](https://ai.google.dev/api/rest) · [Console](https://aistudio.google.com/) |
| `git` | Local git repository operations (CLI wrapper) | Local | Yes | — |
| `github` | GitHub repos, issues, PRs, commits, branches, file content | REST API | Yes | [API Docs](https://docs.github.com/en/rest) · [Site](https://github.com/) |
| `google_apps` | Calendar, Gmail, Keep, Sheets, Tasks, Drive, Translation | REST API (OAuth + API key) | Yes | [API Docs](https://developers.google.com/workspace) · [Console](https://console.cloud.google.com/) |
| `google_drive` | Google Drive — upload, download, export, manage files/folders | REST API (OAuth) | No | [API Docs](https://developers.google.com/drive/api/reference/rest/v3) · [Console](https://console.cloud.google.com/) |
| `grok` | xAI Grok — chat completions, live web search, X post search, embeddings | REST (native SDK) | Yes | [API Docs](https://docs.x.ai/api-reference) · [Console](https://console.x.ai/) |
| `hfl_corpus` | Canonical Homework-for-Life Activity Corpus — entry writes, ES projection status, search, documents, and references | REST API | Yes | [OpenAPI](../../apps/hfl_corpus/openapi.yaml) |
| `investagrams` | Philippine stock analytics | Web scraping | No | [Site](https://www.investagrams.com/) |
| `jira` | Jira project management | REST API (DC/Bearer) | Yes | [API Docs](https://developer.atlassian.com/server/jira/platform/rest-apis/) · [Site](https://www.atlassian.com/software/jira) |
| `justtcg` | Multi-game TCG pricing analytics (MTG, Pokémon, Yu-Gi-Oh!, Lorcana…) — prices + 24h/7d/30d/90d/1y change & trend stats | REST API | Yes | [API Docs](https://justtcg.com/docs) · [Site](https://justtcg.com/) |
| `linkedin` | LinkedIn — profile, posts, sharing | REST API (OAuth2) | Yes | [API Docs](https://learn.microsoft.com/en-gb/linkedin/shared/api-guide/concepts) · [Portal](https://www.linkedin.com/developers/apps) |
| `moo` | Futu/Moo trading stub | Stub | No | [API Docs](https://openapi.futunn.com/futu-api-doc/en/) · [Site](https://www.futunn.com/) |
| `mpc` | MakePlayingCards.com proxy-card autofill (Playwright port of mpc-autofill — saves projects, never checks out) | Browser automation | Yes | [Upstream](https://github.com/chilli-axe/mpc-autofill) · [Site](https://www.makeplayingcards.com/) |
| `notion` | Notion — pages, databases, blocks, search | REST API | Yes | [API Docs](https://developers.notion.com/reference/intro) · [Site](https://www.notion.so/) |
| `oanda` | Forex trading | REST API | Yes | [API Docs](https://developer.oanda.com/rest-live-v20/introduction/) · [Site](https://www.oanda.com/) |
| `open_ai` | OpenAI — Responses API, Code Interpreter, Assistants v2 (deprecated) | REST (native SDK) | Yes | [API Docs](https://platform.openai.com/docs/api-reference) · [Site](https://platform.openai.com/) |
| `orgo` | Cloud VM desktop control for AI agents | REST API | Yes | [API Docs](https://docs.orgo.ai/api-reference/introduction) · [Site](https://orgo.ai/) |
| `own_tracks` | GPS location tracking | REST API + Docker/MQTT | Yes | [API Docs](https://owntracks.org/booklet/tech/http/) · [Site](https://owntracks.org/) |
| `perplexity` | Perplexity Sonar — chat with live web search, search API, embeddings | REST API | Yes | [API Docs](https://docs.perplexity.ai/) · [Site](https://www.perplexity.ai/) |
| `plaud` | Plaud AI voice recorder — recordings + transcripts (cloud API, export-folder fallback) | Adapter | Smoke | [Dev API](https://docs.plaud.ai/) · [Site](https://www.plaud.ai/) |
| `playwright` | Headless browser automation — screenshot, click, fill, evaluate | Local | No | [Docs](https://playwright.dev/python/) |
| `pokemon_tcg` | Pokemon TCG card database — cards by National Dex number, sets, rarities (+ offline JSON-dump fallback) | REST API | Yes | [API Docs](https://docs.pokemontcg.io) · [Site](https://pokemontcg.io/) |
| `rainmeter` | Windows desktop HUD skinning | Local | Yes | [Docs](https://docs.rainmeter.net/) · [Site](https://www.rainmeter.net/) |
| `reddit` | Reddit — subreddits, posts, comments, inbox | REST API (OAuth2) | Yes | [API Docs](https://www.reddit.com/dev/api/) · [Apps](https://www.reddit.com/prefs/apps) |
| `scryfall` | MTG card database | REST API | Yes | [API Docs](https://scryfall.com/docs/api) · [Site](https://scryfall.com/) |
| `spotify` | Spotify listening history — recently-played, top tracks/artists | REST API (OAuth2) | Yes | [API Docs](https://developer.spotify.com/documentation/web-api) · [Dashboard](https://developer.spotify.com/dashboard) |
| `sqlite_vec` | Local vector store — persist embeddings + KNN search for RAG (upsert/search/stats), no server | Local | Yes | [Upstream](https://github.com/asg017/sqlite-vec) |
| `stripe` | Stripe payments — balance, charges, customers, invoices, subscriptions, events | REST API | Yes | [API Docs](https://docs.stripe.com/api) · [Dashboard](https://dashboard.stripe.com/) |
| `tcg_mp` | TCG Marketplace | REST API | Yes | [Site](https://thetcgmarketplace.com/) |
| `telegram` | Telegram Bot messaging | REST API | Yes | [API Docs](https://core.telegram.org/bots/api) · [Site](https://telegram.org/) |
| `trello` | Kanban board management | REST API | Yes | [API Docs](https://developer.atlassian.com/cloud/trello/rest/) · [Site](https://trello.com/) |
| `typesafe` | Jev typed decisions for Hermes | REST API | Yes | [API Docs](https://docs.typesafe.ai/) · [Site](https://typesafe.ai/) |
| `ynab` | Personal budgeting | REST API | Yes | [API Docs](https://api.ynab.com/) · [Site](https://www.ynab.com/) |
| `youtube` | YouTube channels, videos, playlists, search, and targeted Studio analytics | REST API (OAuth2) | Yes | [Data API](https://developers.google.com/youtube/v3/docs) · [Analytics API](https://developers.google.com/youtube/analytics) |

---
