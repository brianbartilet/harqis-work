"""
workflows/tcg/tasks/pokedex_proxies.py

Pokedex proxy-printing pipeline: render a placeholder proxy card for every
National Dex Pokemon (name, dex number, typing, and a checkbox list of its
full-art / Illustration Rare / SIR / special printings) and upload them as
saved makeplayingcards.com projects for manual checkout.

Chained apps: pokemondb.net scrape (BS4) → apps/pokemon_tcg (printings +
rarities, offline-dump fallback) → PokeAPI sprites (artwork) → Playwright
HTML rendering → apps/mpc (order XML + Playwright autofill driver).

Manual trigger only — run via the orchestrator task
``run_pokedex_proxy_pipeline`` or stage-by-stage from
``workflows/tcg/tests/test_pokedex_proxies.py``. No beat schedule.
"""
import base64
import json
import re
import time
import unicodedata
from pathlib import Path
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger
from apps.apps_config import CONFIG_MANAGER

from apps.mpc.references.dto.order import build_orders as build_mpc_orders
from apps.mpc.references.web.constants import CARD_HEIGHT_PX, CARD_WIDTH_PX, Cardstocks
from apps.mpc.references.web.driver import MpcAutofillDriver
from apps.mpc.references.xml.order_xml import read_order_xml, write_order_xml
from apps.pokemon_tcg.references.data.dump import PokemonTcgDataDump
from apps.pokemon_tcg.references.web.api.cards import ApiServicePokemonTcgCards

_log = create_logger("tcg.pokedex_proxies")

# Generated artifacts are consolidated under the repo-root results/ sink
# (results/tcg/pokemon/output/), tracked-but-ignored like every other output.
# Templates remain source, alongside this package.
OUTPUT_DIR = Path(__file__).resolve().parents[3] / "results" / "tcg" / "pokemon" / "output"
TEMPLATES_DIR = Path(__file__).parents[1] / "templates"

POKEDEX_URL = "https://pokemondb.net/pokedex/all"
ARTWORK_URL = ("https://raw.githubusercontent.com/PokeAPI/sprites/master/"
               "sprites/pokemon/other/official-artwork/{dex}.png")
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

#: Priority chase rarities — always listed first on the card.
TIER_1_RARITIES = [
    "Illustration Rare",
    "Special Illustration Rare",
    "Ultra Rare",
    "Rare Ultra",
    "Hyper Rare",
    "Rare Secret",
    "Rare Rainbow",
]
#: Also-wanted rarities — appended after every tier-1 entry.
TIER_2_RARITIES = [
    "Trainer Gallery Rare Holo",
    "Shiny Rare",
    "Shiny Ultra Rare",
    "Amazing Rare",
    "Radiant Rare",
    "Promo",
    "Rare Holo Star",
    "Rare Shining",
]

#: Max printings listed on a card before "+X more".
MAX_PRINTINGS_ON_CARD = 10

#: Standard Pokemon type colors (community-canonical hex values).
TYPE_COLORS = {
    "Normal": "#A8A77A", "Fire": "#EE8130", "Water": "#6390F0",
    "Electric": "#F7D02C", "Grass": "#7AC74C", "Ice": "#96D9D6",
    "Fighting": "#C22E28", "Poison": "#A33EA1", "Ground": "#E2BF65",
    "Flying": "#A98FF3", "Psychic": "#F95587", "Bug": "#A6B91A",
    "Rock": "#B6A136", "Ghost": "#735797", "Dragon": "#6F35FC",
    "Dark": "#705746", "Steel": "#B7B7CE", "Fairy": "#D685AD",
}


# ── helpers ───────────────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    """'Farfetch'd' → 'farfetchd', 'Mr. Mime' → 'mr-mime' (filename-safe)."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    ascii_name = ascii_name.replace("'", "")
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


def darken(hex_color: str, factor: float = 0.65) -> str:
    """Darken a '#rrggbb' color for gradients/badges."""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return f"#{int(r * factor):02x}{int(g * factor):02x}{int(b * factor):02x}"


def parse_pokedex_html(html: str) -> List[dict]:
    """Parse pokemondb's all-Pokemon table into base-form dex entries.

    The table repeats a dex number for every form (Mega/Alolan/…) — the first
    row per number is the base form, which is the one we keep.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="pokedex")
    entries: dict[int, dict] = {}
    for row in table.tbody.find_all("tr"):
        cells = row.find_all("td")
        number = int(cells[0].get_text(strip=True))
        if number in entries:
            continue   # later rows for a number are alternate forms
        name_link = cells[1].find("a", class_="ent-name")
        types = [a.get_text(strip=True) for a in cells[2].find_all("a")]
        entries[number] = {
            "dex_number": number,
            "name": name_link.get_text(strip=True),
            "types": types,
        }
    return [entries[n] for n in sorted(entries)]


def tier_of(rarity: Optional[str]) -> Optional[int]:
    """1 / 2 for wanted rarities, None for everything else."""
    if rarity in TIER_1_RARITIES:
        return 1
    if rarity in TIER_2_RARITIES:
        return 2
    return None


def sort_printings(printings: List[dict]) -> List[dict]:
    """Tier 1 before tier 2; newest set first within each tier."""
    return sorted(printings,
                  key=lambda p: (p["tier"], _negate_date(p.get("release_date") or "")))


def _negate_date(date_str: str) -> str:
    """Map 'YYYY/MM/DD' to a string that sorts newest-first ascending."""
    return "".join(chr(255 - ord(ch)) for ch in date_str) if date_str else "￿"


def _cards_to_printings(cards) -> List[dict]:
    """Project DtoPokemonTcgCard objects onto the card-face printing entries."""
    printings = []
    for card in cards:
        tier = tier_of(card.rarity)
        if tier is None:
            continue
        set_obj = card.set if isinstance(card.set, dict) else {}
        printings.append({
            "card_id": card.id,
            "set_id": set_obj.get("id"),
            "set_name": set_obj.get("name") or "Unknown Set",
            "number": card.number,
            "rarity": card.rarity,
            "release_date": set_obj.get("releaseDate") or "",
            "tier": tier,
        })
    return sort_printings(printings)


def _artwork_data_uri(dex_number: int, artwork_dir: Path,
                      session: requests.Session) -> str:
    """Download (once) and base64-embed the official artwork; '' on failure."""
    artwork_dir.mkdir(parents=True, exist_ok=True)
    path = artwork_dir / f"{dex_number}.png"
    if not path.is_file():
        try:
            resp = session.get(ARTWORK_URL.format(dex=dex_number), timeout=30)
            resp.raise_for_status()
            path.write_bytes(resp.content)
        except requests.RequestException as e:
            _log.warning("No artwork for #%04d: %s", dex_number, e)
            return ""
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def _render_html_to_png(page, html: str, output_path: Path) -> None:
    page.set_content(html)
    page.wait_for_load_state("networkidle")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(output_path))


def pick_preview_dex_numbers(printings_by_dex: dict, sample_size: int = 10) -> List[int]:
    """Preview set: Charizard (heavy case) + popular picks + no-prints cases."""
    chosen = [6, 25, 1, 150, 151]                                   # the heavy/popular picks
    chosen += [int(d) for d, p in printings_by_dex.items() if not p][:3]   # no-prints cases
    chosen += sorted((int(d) for d in printings_by_dex),
                     key=lambda d: -len(printings_by_dex[str(d)]))  # heaviest lists as filler
    seen, preview = set(), []
    for dex in chosen:
        if dex not in seen and str(dex) in printings_by_dex:
            seen.add(dex)
            preview.append(dex)
        if len(preview) >= sample_size:
            break
    return preview


# ── stage 1: base dex ─────────────────────────────────────────────────────────

@SPROUT.task()
@log_result()
def build_pokedex(**kwargs):
    """Scrape pokemondb.net/pokedex/all into output/pokedex.json (~1025 base forms).

    Args:
        output_dir: Override the workflow output directory.

    Returns:
        Summary string with the entry count and cache path.
    """
    output_dir = Path(kwargs.get("output_dir", OUTPUT_DIR))
    resp = requests.get(POKEDEX_URL, headers={"User-Agent": USER_AGENT}, timeout=60)
    resp.raise_for_status()
    entries = parse_pokedex_html(resp.text)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache = output_dir / "pokedex.json"
    cache.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    _log.info("build_pokedex: %d base-form entries -> %s", len(entries), cache)
    return f"{len(entries)} dex entries cached at {cache}"


# ── stage 2: chase printings ──────────────────────────────────────────────────

@SPROUT.task()
@log_result()
def fetch_printings(**kwargs):
    """Fetch each Pokemon's tier-1/tier-2 printings into output/printings.json.

    Queries the Pokemon TCG API once per dex number (retry with backoff,
    falling back to the offline pokemon-tcg-data dump when configured), then
    filters/sorts client-side. Resumable: already-fetched dex numbers are
    skipped on re-run.

    Args:
        cfg_id__pokemon_tcg: Config key for the Pokemon TCG app (default 'POKEMON_TCG').
        dex_numbers:         Optional explicit list (default: all from pokedex.json).
        request_interval_s:  Pacing between API calls (default 2.2 — keyless limit).
        output_dir:          Override the workflow output directory.

    Returns:
        Summary string; failures are collected per dex number, never raised.
    """
    cfg_id = kwargs.get("cfg_id__pokemon_tcg", "POKEMON_TCG")
    output_dir = Path(kwargs.get("output_dir", OUTPUT_DIR))
    interval = float(kwargs.get("request_interval_s", 2.2))
    cfg = CONFIG_MANAGER.get(cfg_id)

    pokedex = json.loads((output_dir / "pokedex.json").read_text(encoding="utf-8"))
    dex_numbers = kwargs.get("dex_numbers") or [e["dex_number"] for e in pokedex]

    cache_path = output_dir / "printings.json"
    printings_by_dex: dict = (
        json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.is_file() else {})

    api = ApiServicePokemonTcgCards(cfg)
    dump = PokemonTcgDataDump((cfg.app_data or {}).get("dump_path"))
    wanted = TIER_1_RARITIES + TIER_2_RARITIES
    failures: List[int] = []

    todo = [d for d in dex_numbers if str(d) not in printings_by_dex]
    _log.info("fetch_printings: %d to fetch (%d already cached)",
              len(todo), len(printings_by_dex))
    for i, dex in enumerate(todo):
        cards, last_error = None, None
        for attempt in range(3):
            try:
                cards = api.search_cards_by_dex_number(dex)
                if not isinstance(cards, list):    # raw Response = request failed
                    raise RuntimeError(f"unexpected API response: {cards!r}")
                break
            except Exception as e:                  # noqa: BLE001 — collected, not raised
                last_error = e
                time.sleep(interval * (2 ** attempt))
        if cards is None and dump.is_available():
            _log.warning("fetch_printings: API failed for #%04d (%s) — using dump",
                         dex, last_error)
            cards = dump.find_cards(dex_number=dex, rarities=wanted)
        if cards is None:
            _log.warning("fetch_printings: #%04d failed entirely: %s", dex, last_error)
            failures.append(dex)
            continue
        printings_by_dex[str(dex)] = _cards_to_printings(cards)
        if (i + 1) % 25 == 0 or i == len(todo) - 1:
            cache_path.write_text(json.dumps(printings_by_dex, indent=1), encoding="utf-8")
            _log.info("fetch_printings: %d/%d done", i + 1, len(todo))
        time.sleep(interval)

    cache_path.write_text(json.dumps(printings_by_dex, indent=1), encoding="utf-8")
    summary = (f"{len(printings_by_dex)} dex entries with printings cached at "
               f"{cache_path}; {len(failures)} failure(s)"
               + (f": {failures[:20]}" if failures else ""))
    _log.info("fetch_printings: %s", summary)
    return summary


# ── stage 3: render card images ───────────────────────────────────────────────

@SPROUT.task()
@log_result()
def render_cards(**kwargs):
    """Render card fronts (and the Pokeball cardback) at 822x1122 px.

    Args:
        preview:     True renders ~10 representative samples (Charizard, a
                     no-prints case, …) into output/preview/ for sign-off.
        dex_numbers: Optional explicit list (overrides preview selection).
        output_dir:  Override the workflow output directory.

    Returns:
        Summary string with the rendered count and target directory.
    """
    from jinja2 import Template
    from playwright.sync_api import sync_playwright

    preview = bool(kwargs.get("preview", False))
    output_dir = Path(kwargs.get("output_dir", OUTPUT_DIR))

    pokedex = {e["dex_number"]: e for e in
               json.loads((output_dir / "pokedex.json").read_text(encoding="utf-8"))}
    printings_by_dex = json.loads(
        (output_dir / "printings.json").read_text(encoding="utf-8"))

    dex_numbers = kwargs.get("dex_numbers")
    if dex_numbers is None:
        dex_numbers = (pick_preview_dex_numbers(printings_by_dex) if preview
                       else sorted(pokedex))
    cards_dir = output_dir / ("preview" if preview else "cards")
    artwork_dir = output_dir / "artwork"

    front_template = Template((TEMPLATES_DIR / "card_front.html").read_text(encoding="utf-8"))
    back_html = (TEMPLATES_DIR / "card_back.html").read_text(encoding="utf-8")

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    rendered = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": CARD_WIDTH_PX, "height": CARD_HEIGHT_PX})
        for dex in dex_numbers:
            entry = pokedex.get(int(dex))
            if entry is None:
                _log.warning("render_cards: no pokedex entry for #%s — skipping", dex)
                continue
            printings = printings_by_dex.get(str(dex), [])
            shown = printings[:MAX_PRINTINGS_ON_CARD]
            primary_color = TYPE_COLORS.get(entry["types"][0], "#A8A77A")
            html = front_template.render(
                name=entry["name"],
                dex_number=entry["dex_number"],
                types=entry["types"],
                type_color=primary_color,
                type_color_dark=darken(primary_color),
                artwork_data_uri=_artwork_data_uri(int(dex), artwork_dir, session),
                printings=shown,
                more_count=max(0, len(printings) - len(shown)),
                has_printings=bool(printings),
            )
            out = cards_dir / f"{entry['dex_number']:04d}-{slugify(entry['name'])}.png"
            _render_html_to_png(page, html, out)
            rendered += 1
            if rendered % 50 == 0:
                _log.info("render_cards: %d/%d rendered", rendered, len(dex_numbers))

        _render_html_to_png(page, back_html, output_dir / "cardback.png")
        browser.close()

    summary = f"{rendered} front(s) + cardback rendered into {cards_dir}"
    _log.info("render_cards: %s", summary)
    return summary


# ── stage 4: order XMLs ───────────────────────────────────────────────────────

@SPROUT.task()
@log_result()
def build_order_xmls(**kwargs):
    """Pack rendered fronts into mpc-autofill order XML(s), split at 612 cards.

    Args:
        stock:      MPC cardstock (default '(S30) Standard Smooth').
        output_dir: Override the workflow output directory.

    Returns:
        Summary string listing the XML path(s) and any validation problems.
    """
    output_dir = Path(kwargs.get("output_dir", OUTPUT_DIR))
    stock = kwargs.get("stock", Cardstocks.S30.value)
    cards_dir = output_dir / "cards"
    fronts = sorted(str(p) for p in cards_dir.glob("*.png"))
    if not fronts:
        _log.warning("build_order_xmls: no rendered fronts in %s", cards_dir)
        return f"No fronts found in {cards_dir} — run render_cards first"

    orders = build_mpc_orders(fronts, str(output_dir / "cardback.png"),
                              stock=stock, name_prefix="Pokedex Proxies")
    results = []
    for n, order in enumerate(orders, start=1):
        xml_path = output_dir / f"pokedex_proxies_{n}.xml"
        write_order_xml(order, str(xml_path))
        problems = order.validate()
        results.append(f"{xml_path} ({order.details.quantity} cards"
                       + (f", PROBLEMS: {problems}" if problems else ") OK"))
    summary = f"{len(orders)} order(s): " + "; ".join(results)
    _log.info("build_order_xmls: %s", summary)
    return summary


# ── stage 5: MPC upload ───────────────────────────────────────────────────────

@SPROUT.task()
@log_result()
def upload_to_mpc(**kwargs):
    """Autofill each order XML into a saved MPC project (headed browser).

    Ends with the project(s) in *Saved Projects* — review, add to cart, and
    pay manually in the browser window that stays open. Never checks out.

    Args:
        cfg_id__mpc:         Config key for the MPC app (default 'MPC').
        xml_paths:           Optional explicit list (default: output/pokedex_proxies_*.xml).
        auto_save_threshold: Save cadence during inserts (default 5).
        output_dir:          Override the workflow output directory.

    Returns:
        Summary string with the saved project names.
    """
    cfg_id = kwargs.get("cfg_id__mpc", "MPC")
    output_dir = Path(kwargs.get("output_dir", OUTPUT_DIR))
    cfg = CONFIG_MANAGER.get(cfg_id)
    xml_paths = kwargs.get("xml_paths") or sorted(
        str(p) for p in output_dir.glob("pokedex_proxies_*.xml"))
    if not xml_paths:
        return f"No order XMLs in {output_dir} — run build_order_xmls first"

    driver = MpcAutofillDriver(config=cfg if isinstance(cfg, dict) else cfg.__dict__,
                               headless=False)
    driver.launch()
    saved = []
    for xml_path in xml_paths:
        order = read_order_xml(xml_path)
        _log.info("upload_to_mpc: autofilling '%s' (%d cards)",
                  order.name, order.details.quantity)
        driver.execute_order(order, auto_save_threshold=int(
            kwargs.get("auto_save_threshold", 5)))
        saved.append(order.name)
    # Browser intentionally left open for manual review + checkout.
    summary = (f"{len(saved)} project(s) saved to the MPC account: {saved}. "
               "Review and check out manually in the open browser.")
    _log.info("upload_to_mpc: %s", summary)
    return summary


# ── orchestrator ──────────────────────────────────────────────────────────────

@SPROUT.task()
@log_result()
def run_pokedex_proxy_pipeline(**kwargs):
    """Run the full pipeline: dex → printings → render → order XMLs [→ MPC].

    Args:
        preview:    True (default) stops after rendering ~10 samples into
                    output/preview/ for visual sign-off — no orders, no MPC.
        upload:     False (default) skips the MPC browser stage even on a full
                    run, leaving the order XMLs ready for upload_to_mpc.
        (Stage kwargs — cfg_id__pokemon_tcg, cfg_id__mpc, request_interval_s,
         stock, output_dir — are passed through.)

    Returns:
        Combined summary of every stage that ran.
    """
    preview = bool(kwargs.get("preview", True))
    upload = bool(kwargs.get("upload", False))
    results = [build_pokedex(**kwargs)]
    if preview:
        sample = [1, 6, 10, 13, 25, 150, 151]   # includes likely no-print bugs/birds
        results.append(fetch_printings(**{**kwargs, "dex_numbers": sample}))
        results.append(render_cards(**{**kwargs, "preview": True}))
        results.append("PREVIEW ONLY — inspect output/preview/, then re-run "
                       "with preview=False")
        return " | ".join(results)
    results.append(fetch_printings(**kwargs))
    results.append(render_cards(**{**kwargs, "preview": False}))
    results.append(build_order_xmls(**kwargs))
    if upload:
        results.append(upload_to_mpc(**kwargs))
    else:
        results.append("MPC upload skipped (upload=False) — run upload_to_mpc "
                       "when ready")
    return " | ".join(results)
