# JustTCG

## Description

[JustTCG](https://justtcg.com/) is a real-time **TCG pricing API** covering Magic: The Gathering,
Pokémon, Yu-Gi-Oh!, Disney Lorcana, One Piece TCG, Digimon, and Union Arena. This integration wraps
the v1 REST API (`https://api.justtcg.com/v1`) to power pricing analytics — current prices plus
24h / 7d / 30d / 90d / 1y / all-time change, trend, and volatility statistics per card variant.

- **API docs:** https://justtcg.com/docs · [Quickstart](https://justtcg.com/docs/quickstart)
- **Authentication:** API key in the custom `x-api-key` header (key format `tcg_...`). No Bearer token.
- **Plans / rate limits:** every response includes a `_metadata` block with `apiPlan` and
  `apiRequestsRemaining`. Batch size cap is plan-dependent: 20 (Free) / 100 (Starter & Pro) /
  200 (Enterprise).

## Supported Automations

- [x] webservices — REST API calls
- [ ] browser — Selenium page automation
- [ ] desktop — Local Windows automation
- [ ] mobile — Android/iOS automation
- [ ] internet of things — MQTT / hardware integration

## Directory Structure

```
apps/justtcg/
├── __init__.py
├── config.py                          # Loads the JUSTTCG section from apps_config.yaml
├── mcp.py                             # FastMCP tool registrations
├── references/
│   ├── dto/
│   │   ├── game.py                    # DtoJusttcgGame
│   │   ├── set.py                     # DtoJusttcgSet
│   │   └── card.py                    # DtoJusttcgCard + DtoJusttcgVariant (pricing/analytics)
│   └── web/
│       ├── base_api_service.py        # BaseApiServiceJusttcg (x-api-key auth)
│       └── api/
│           ├── games.py               # ApiServiceJusttcgGames
│           ├── sets.py                # ApiServiceJusttcgSets
│           └── cards.py               # ApiServiceJusttcgCards (lookup / search / batch)
└── tests/
    ├── test_games.py
    ├── test_sets.py
    └── test_cards.py
```

## Configuration

Add this section to `apps_config.yaml`:

```yaml
JUSTTCG:
  app_id: 'justtcg'
  client: 'rest'
  parameters:
    base_url: 'https://api.justtcg.com/v1/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 60
    stream: False
  app_data:
    api_key: ${JUSTTCG_API_KEY}
  return_data_only: True
```

Add the required env var to `.env/apps.env`:

```env
JUSTTCG_API_KEY=        # your JustTCG API key (tcg_...) from https://justtcg.com/dashboard
```

## Available Services

| Service class | Method | Description |
|---|---|---|
| `ApiServiceJusttcgGames` | `list_games()` | All supported games + aggregate value / sealed stats |
| `ApiServiceJusttcgSets` | `list_sets(game, q, limit, offset)` | Sets within a game (filter by game id / name) |
| `ApiServiceJusttcgCards` | `get_card(card_id, variant_id, tcgplayer_id, mtgjson_id, scryfall_id, tcgplayer_sku_id, condition, printing)` | Single card lookup by any identifier; returns priced variants |
| `ApiServiceJusttcgCards` | `search_cards(q, game, set, condition, printing, order_by, order, limit, offset)` | Search / browse, sorted by price or price-movement window |
| `ApiServiceJusttcgCards` | `batch_cards(items)` | Batch lookup of up to 200 cards/variants in one POST |

All card methods return `List[DtoJusttcgCard]`; pricing lives on each card's `variants` (raw dicts).
Call `DtoJusttcgCard.variant_dtos()` for typed `DtoJusttcgVariant` access to the analytics fields.

## MCP Tools

| Tool | Args | Description |
|---|---|---|
| `list_justtcg_games` | — | List all supported games with value stats |
| `list_justtcg_sets` | `game?`, `q?`, `limit?`, `offset?` | List sets, optionally filtered by game / name |
| `get_justtcg_card` | `card_id?`, `variant_id?`, `tcgplayer_id?`, `condition?`, `printing?` | Look up one card + its priced variants |
| `search_justtcg_cards` | `q?`, `game?`, `set_id?`, `condition?`, `printing?`, `order_by?`, `order?`, `limit?`, `offset?` | Search/browse cards; sort by `order_by` ('price'/'24h'/'7d'/'30d') for biggest movers |
| `batch_justtcg_cards` | `items` | Batch lookup (plan cap 20/100/200) |

## Tests

Live integration tests (no mocking) — they require a valid `JUSTTCG_API_KEY`.

```sh
pytest apps/justtcg/tests/              # all (≈40s — paced for the free tier)
pytest apps/justtcg/tests/ -m smoke     # fast read-only checks
pytest apps/justtcg/tests/ -m sanity    # broader coverage (search + lookup + batch)
```

`tests/conftest.py` paces every call to stay under the **Free Tier's 10 requests/minute**
limit, retries on HTTP 429 with exponential backoff (honouring `Retry-After`), and *skips*
(rather than fails) if the limit can't be cleared. On a paid tier, speed the suite up by
lowering the spacing: `JUSTTCG_TEST_MIN_INTERVAL=1 pytest apps/justtcg/tests/`.

## Notes

- **Auth header is `x-api-key`** — not `Authorization: Bearer`. The base service injects it from
  `config.app_data['api_key']`.
- **Pricing is per-variant.** A card carries identity/metadata; each variant (condition + printing +
  language) holds the price and the full analytics suite (`priceChange7d`, `avgPrice`, `minPrice7d`,
  `trendSlope7d`, `priceRelativeTo30dRange`, `minPriceAllTime`, …).
- **Sorting for analytics:** `search_cards(order_by='7d', order='desc')` surfaces the week's biggest
  movers within a game/set.
- **Identifier precedence** on `get_card`: `variantId > tcgplayerSkuId > tcgplayerId > mtgjsonId >
  scryfallId > cardId`. `condition`/`printing` filters are ignored when a SKU/variant id is supplied.
- **Pagination:** responses carry a `meta` block (`total`, `limit`, `offset`, `hasMore`). Increase
  `offset` to page; the service returns just the `data` array (the framework unwraps the envelope).
- **`/sets` requires a game.** `list_sets()` with no `game` returns HTTP 400 — always pass `game=`.
- **Rate limits (per minute):** Free 10 · Starter 50 · Pro 100 · Enterprise 500 (plus daily/monthly
  caps: Free 100/day, 1,000/month). On HTTP 429 the docs recommend exponential backoff with jitter
  honouring `Retry-After`. On an error/429 the deserializer returns the raw `Response` instead of a
  list, so callers should check `isinstance(result, list)` before consuming it.
- **Quota:** watch `_metadata.apiRequestsRemaining`; prefer `batch_cards` over many single lookups.
