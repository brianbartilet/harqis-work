# Apify

## Description

Wraps the [Apify REST API v2](https://docs.apify.com/api/v2) — a web-scraping and automation platform whose unit of execution is an *actor* (a pre-built or custom scraper hosted on Apify). Authentication is a single Bearer token created on the [Integrations page](https://console.apify.com/account#/integrations).

This integration covers two layers:

1. **Generic actor / run / dataset access** — call any actor (sync or async), poll runs, fetch dataset items, list key-value records.
2. **Trends helpers** — convenience wrappers around well-known public actors (Google Trends, Instagram, Facebook, TikTok, Reddit) for market research and social-media aggregation, plus a single `aggregate_trends()` call that fans one query out across multiple platforms and projects results onto a normalised shape.

## Supported Automations

- [x] webservices — REST API calls
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] internet of things

## Directory Structure

```
apps/apify/
├── __init__.py
├── config.py                            # Loads APIFY section from apps_config.yaml
├── mcp.py                               # FastMCP tool registrations
├── README.md
├── references/
│   ├── dto/
│   │   ├── actor.py                     # DtoApifyActor, DtoApifyActorRun
│   │   ├── dataset.py                   # DtoApifyDataset
│   │   └── trend.py                     # DtoApifyTrendItem (normalised cross-platform shape)
│   └── web/
│       ├── base_api_service.py          # BaseApiServiceApify — Bearer auth + actor-id encoding
│       └── api/
│           ├── actors.py                # list / get / run / run-sync / abort
│           ├── runs.py                  # account-wide run inspection + log fetch
│           ├── datasets.py              # dataset metadata + items
│           ├── key_value_stores.py      # KV records
│           └── trends.py                # Google Trends, IG, FB, TikTok, Reddit + aggregate
└── tests/
    ├── test_actors.py                   # smoke checks for actors/runs/datasets list endpoints
    └── test_trends.py                   # sanity checks (consume Apify compute units)
```

## Configuration

`apps_config.yaml`:

```yaml
APIFY:
  app_id: 'apify'
  client: 'rest'
  parameters:
    base_url: 'https://api.apify.com/v2/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 300
    stream: False
  app_data:
    api_key: ${APIFY_API_KEY}
  return_data_only: True
```

`.env/apps.env`:

```env
APIFY_API_KEY=your_token_here
```

The `timeout: 300` matches the Apify sync-run hard cap (5 minutes).

## Available Services

| Service class | Module | Purpose |
|---|---|---|
| `ApiServiceApifyActors` | `references/web/api/actors.py` | List actors, run an actor sync (`run_actor_sync`) or async (`run_actor`), abort a run |
| `ApiServiceApifyRuns` | `references/web/api/runs.py` | List recent runs, fetch a run's status and stats, stream the run log |
| `ApiServiceApifyDatasets` | `references/web/api/datasets.py` | List datasets, fetch dataset items (paginated, with field whitelisting) |
| `ApiServiceApifyKeyValueStores` | `references/web/api/key_value_stores.py` | List stores, list keys, fetch raw record values |
| `ApiServiceApifyTrends` | `references/web/api/trends.py` | High-level wrappers: `search_google_trends`, `search_instagram_hashtag`, `search_facebook_posts`, `search_tiktok`, `search_reddit`, `aggregate_trends` |

## MCP Tools

See [`mcp.py`](mcp.py) for the full list. Headline tools:

| Tool | Description |
|---|---|
| `apify_list_actors` | Browse available actors |
| `apify_get_actor` | Metadata for one actor |
| `apify_run_actor_sync` | Run any actor synchronously, return dataset items |
| `apify_run_actor` | Start an async run, returns run object for later polling |
| `apify_list_runs` / `apify_get_run` | Inspect runs across the account |
| `apify_get_dataset_items` | Fetch records from a finished run's `defaultDatasetId` |
| `apify_google_trends` | Trending keywords by location + time window |
| `apify_instagram_hashtag` | Recent IG posts for a hashtag |
| `apify_facebook_posts` | Recent FB posts from pages or queries |
| `apify_tiktok` | Recent TikTok videos by hashtag/keyword |
| `apify_reddit` | Reddit search across subreddits |
| `apify_aggregate_trends` | Run one query across all five platforms, return normalised items |
| `apify_default_actors` | Show the actor IDs the trends helpers default to |

## Default Actors

The trends helpers ship with these public actors hardcoded in `trends.py:DEFAULT_ACTORS`:

| Platform | Actor ID |
|---|---|
| Google Trends | `apify/google-trends-scraper` |
| Instagram | `apify/instagram-hashtag-scraper` |
| Facebook | `apify/facebook-posts-scraper` |
| TikTok | `clockworks/free-tiktok-scraper` |
| Reddit | `trudax/reddit-scraper-lite` |

Override per-call by passing `actor_id=...` to any `search_*` method, or edit the dict to swap to a private/premium actor across the codebase.

## Adding a new actor wrapper

The full Apify Store has thousands of actors. Wrapping a new one is just a one-method addition:

1. Find the actor on https://apify.com/store and note its ID and input schema.
2. Add a method to `references/web/api/trends.py` (or a new file for an unrelated category) that builds the right `payload` and calls `self._actors.run_actor_sync(actor_id, payload)`.
3. Optionally expose it as an MCP tool by adding a `@mcp.tool()` wrapper in `mcp.py`.

## Tests

```sh
pytest apps/apify/tests/ -m smoke      # cheap list calls, no actor execution
pytest apps/apify/tests/ -m sanity     # runs actors, consumes compute units
```

All tests are live and require a valid `APIFY_API_KEY`.

## Notes

- **Compute costs.** Every actor run consumes Apify Compute Units (CUs). The free plan grants $5 of usage per month — enough to experiment with the trends helpers a few dozen times. The sync helpers are billed the same as async runs; the only difference is who waits for the result.
- **Sync vs async.** `run_actor_sync` blocks for up to 5 minutes (or `timeout_secs`). Past that, fall back to `run_actor` + polling `get_run` until `status == 'SUCCEEDED'`, then `get_dataset_items(run.defaultDatasetId)`.
- **Actor IDs.** The canonical form is `username/actor-name` (e.g. `apify/google-trends-scraper`). The base service auto-encodes the slash to `~` for URL safety — you can pass either form.
- **Input schemas vary.** Every actor defines its own input shape. The trends wrappers normalise the most common cases; for anything else use `apify_run_actor_sync` and pass `input_payload` directly per the actor's docs.
- **Rate-limit headers.** The API returns `X-RateLimit-Limit` and `X-RateLimit-Remaining` headers. Long polling loops should respect them.
