# TCG Workflows

Card-game pipelines. First (and currently only) resident: the **Pokedex
proxy-printing pipeline** — a placeholder proxy card for every National Dex
Pokemon, uploaded as saved makeplayingcards.com projects, used as physical
slot-holders while collecting each Pokemon's full-art / Illustration Rare /
SIR / special printings.

### `run_pokedex_proxy_pipeline` (+ its five stages)

**Goal:** Render ~1025 proxy card fronts (name, dex number, typing, checkbox
list of chase printings) + a Pokeball cardback, pack them into ≤612-card MPC
orders, and autofill them into saved MPC projects for manual checkout.

**Apps chained:**
1. `pokemondb.net/pokedex/all` (BS4 scrape) → base dex: number, name, types (forms deduped)
2. `apps/pokemon_tcg` → per-dex printings, tier-filtered & newest-first
   (offline `pokemon-tcg-data` dump as fallback)
3. PokeAPI sprites (GitHub raw) → official artwork per Pokemon
4. Playwright + `templates/card_front.html` → 822×1122 px card PNGs
5. `apps/mpc` → order XML(s) split at 612 + Playwright autofill into saved projects

All generated artifacts land under `results/tcg/pokemon/output/` (the repo-root
`results/` sink — tracked but gitignored). It's shown as `output/` in the table
below; override per call with the `output_dir` kwarg.

**Stages (each its own Celery task, all resumable via `output/` caches):**

| Task | Output |
|------|--------|
| `build_pokedex` | `output/pokedex.json` (~1025 base forms) |
| `fetch_printings` | `output/printings.json` (tiered, newest-first; per-dex failures collected) |
| `render_cards` | `output/cards/*.png` (or `output/preview/` with `preview=True`) + `output/cardback.png` |
| `build_order_xmls` | `output/pokedex_proxies_N.xml` (mpc-autofill-compatible) |
| `upload_to_mpc` | Saved MPC project(s); headed browser left open — **never checks out** |
| `run_pokedex_proxy_pipeline` | Orchestrates the above; `preview=True` (default) stops after ~10 samples |

**Rarity tiers** (the API has no literal "Full Art" — see `apps/pokemon_tcg/README.md`):
- **Tier 1 (listed first):** Illustration Rare, Special Illustration Rare, Ultra Rare,
  Rare Ultra, Hyper Rare, Rare Secret, Rare Rainbow
- **Tier 2 (appended):** Trainer Gallery Rare Holo, Shiny Rare, Shiny Ultra Rare,
  Amazing Rare, Radiant Rare, Promo, Rare Holo Star, Rare Shining
- Max 10 rows per card + "+X more…"; zero qualifying printings → "No special prints yet".

**Schedule:** manual / on-demand only — `WORKFLOW_TCG` ships empty (see
`tasks_config.py` for why). The pytest file is the trigger:

```bash
# 1. Preview — ~10 samples into output/preview/ for visual sign-off:
pytest workflows/tcg/tests/test_pokedex_proxies.py -o addopts="" -k preview -v

# 2. Full run — all ~1025 cards + 2 order XMLs (no MPC):
TCG_FULL_PIPELINE=1 pytest workflows/tcg/tests/test_pokedex_proxies.py -o addopts="" -k full_pipeline -v

# 3. MPC upload — headed browser, saves projects, you check out manually:
TCG_MPC_UPLOAD=1 pytest workflows/tcg/tests/test_pokedex_proxies.py -o addopts="" -k upload -v
```

(`-o addopts=""` lifts pytest.ini's global `--ignore=workflows/`.)

**Queue:** `WorkflowQueue.TCG`

**Required config keys:** `POKEMON_TCG`, `MPC`

**Required env vars:** `MPC_EMAIL`, `MPC_PASSWORD` (upload stage only);
optional `POKEMON_TCG_API_KEY` (raises rate limits), `POKEMON_TCG_DATA_DUMP_PATH`
(offline fallback), `MPC_BROWSER_PROFILE_DIR` (persistent login).

**Data flow:**
```
pokemondb table → pokedex.json → pokemontcg.io (tier filter, newest first)
   → printings.json → Jinja2 + Playwright (822×1122 PNG per Pokemon)
   → order XML ×2 (≤612 each) → MPC autofill → SAVED project → manual checkout
```

**Timing expectations:** `fetch_printings` makes ~1025 API calls at ~2.2 s
keyless pacing (≈ 40 min; set `POKEMON_TCG_API_KEY` and pass
`request_interval_s=0.5` to cut it to ≈ 10 min). Rendering ~1025 cards takes
≈ 15–20 min. The MPC upload runs at the site's pace — expect ≈ 1–2 h per
612-card project; auto-save every 5 inserts makes it resumable.

**Caching / resume:** every stage reads its predecessor's JSON/PNG cache from
`results/tcg/pokemon/output/` (gitignored) and skips work already done — delete a
cache file to force a refresh (e.g. `printings.json` after a new set drops).
