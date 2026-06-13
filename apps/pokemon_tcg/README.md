# Pokemon TCG

## Description

[The Pokemon TCG API](https://pokemontcg.io/) (v2, `https://api.pokemontcg.io/v2/`) is the
canonical free database of every Pokemon TCG card — identity, rarity, set, images, and the
queryable `nationalPokedexNumbers` field that powers the Pokedex proxy-printing pipeline in
`workflows/tcg/`. This integration wraps the cards / sets / rarities endpoints and adds an
offline fallback reader for the official JSON dump
([PokemonTCG/pokemon-tcg-data](https://github.com/PokemonTCG/pokemon-tcg-data)) to hedge the
API's patchy uptime.

- **API docs:** https://docs.pokemontcg.io
- **Authentication:** optional `X-Api-Key` header — keyless works (30 req/min, 1,000/day);
  a free key from https://dev.pokemontcg.io raises the cap to 20,000/day.
- **Rarity caveat:** there is **no "Full Art" rarity string**. Full arts surface as
  `Rare Ultra` (SWSH/XY), `Ultra Rare` (SV ex), `Rare Holo V`, golds as `Hyper Rare`,
  rainbows as `Rare Rainbow`/`Rare Secret`. Always filter with the exact strings from
  `GET /rarities`.

## Supported Automations

- [x] webservices — REST API calls
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] internet of things

## Directory Structure

```
apps/pokemon_tcg/
├── __init__.py
├── config.py                          # Loads the POKEMON_TCG section from apps_config.yaml
├── mcp.py                             # FastMCP tool registrations
├── references/
│   ├── data/
│   │   └── dump.py                    # PokemonTcgDataDump — offline pokemon-tcg-data reader
│   ├── dto/
│   │   ├── card.py                    # DtoPokemonTcgCard (+ set_dto / release_date helpers)
│   │   └── set.py                     # DtoPokemonTcgSet
│   └── web/
│       ├── base_api_service.py        # BaseApiServicePokemonTcg (optional X-Api-Key auth)
│       └── api/
│           ├── cards.py               # ApiServicePokemonTcgCards (search / by-dex / get)
│           ├── sets.py                # ApiServicePokemonTcgSets
│           └── rarities.py            # ApiServicePokemonTcgRarities
└── tests/
    ├── conftest.py                    # rate-limit pacing + outage-skip wrapper
    ├── test_cards.py
    ├── test_sets.py
    ├── test_rarities.py
    └── test_dump.py                   # skips unless POKEMON_TCG_DATA_DUMP_PATH is set
```

## Configuration

Add this section to `apps_config.yaml`:

```yaml
POKEMON_TCG:
  app_id: 'pokemon_tcg'
  client: 'rest'
  parameters:
    base_url: 'https://api.pokemontcg.io/v2/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 60
    stream: False
  app_data:
    api_key: ${POKEMON_TCG_API_KEY}
    dump_path: ${POKEMON_TCG_DATA_DUMP_PATH}
  return_data_only: True
```

And to `.env/apps.env`:

```env
POKEMON_TCG_API_KEY=            # optional — blank falls back to keyless limits
POKEMON_TCG_DATA_DUMP_PATH=     # optional — local clone of PokemonTCG/pokemon-tcg-data
```

## Available Services

| Class | Methods | Purpose |
|-------|---------|---------|
| `ApiServicePokemonTcgCards` | `search_cards(q, page, page_size, order_by, select)` · `search_cards_by_dex_number(dex_number, rarity, …)` · `get_card(card_id)` | Lucene-style card search; by-dex helper sorts newest set first and trims fields via `select` |
| `ApiServicePokemonTcgSets` | `list_sets(q, page, page_size, order_by)` · `get_set(set_id)` | Expansion set catalogue |
| `ApiServicePokemonTcgRarities` | `list_rarities()` | The canonical rarity strings (plain `list[str]`) |
| `PokemonTcgDataDump` | `is_available()` · `load_sets()` · `iter_cards()` · `find_cards(dex_number, rarities)` | Offline drop-in equivalent of the by-dex query, reading the local JSON dump |

## MCP Tools

| Tool | Args | Description |
|------|------|-------------|
| `search_pokemon_tcg_cards` | `q`, `page`, `page_size`, `order_by`, `select` | Lucene-style card search |
| `get_pokemon_tcg_cards_by_dex` | `dex_number`, `rarity` | A Pokemon's printings by National Dex number, newest first |
| `list_pokemon_tcg_sets` | `q`, `order_by` | Expansion sets (newest first by default) |
| `list_pokemon_tcg_rarities` | — | Every exact rarity string the API knows |

## Tests

```bash
pytest apps/pokemon_tcg/tests/ -m smoke      # fast read-only live checks
pytest apps/pokemon_tcg/tests/ -m sanity     # broader coverage
```

No credentials required (keyless tier works); `test_dump.py` skips unless
`POKEMON_TCG_DATA_DUMP_PATH` points at a clone of `PokemonTCG/pokemon-tcg-data`.

## Notes

- **Rate limits:** keyless 30 req/min · 1,000/day; free key 20,000/day. The test conftest
  paces calls and skips (not fails) on sustained 429s/outages.
- **Uptime:** public monitors report ~71% 30-day reliability — production workflows should
  retry with backoff and fall back to `PokemonTcgDataDump`.
- **Data freshness:** the API (and dump) can lag new set releases by several months; the
  newest 2026 sets may be missing.
- **Pagination:** `pageSize` caps at 250; only extreme dex numbers (Pikachu #25) exceed one
  page — pass `page=2+` to continue.
