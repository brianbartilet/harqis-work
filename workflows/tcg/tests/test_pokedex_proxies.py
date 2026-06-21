"""
Tests for the Pokedex proxy-printing pipeline.

The pipeline is manual-trigger by design — these tests ARE the trigger:

    # 1. Preview (~10 sample cards into results/tcg/pokemon/output/preview/):
    pytest workflows/tcg/tests/test_pokedex_proxies.py -k preview -v

    # 2. Full run (all ~1025 cards + order XMLs, no MPC upload):
    TCG_FULL_PIPELINE=1 pytest workflows/tcg/tests/test_pokedex_proxies.py -k full_pipeline -v

    # 3. MPC upload (headed browser, saves projects, manual checkout):
    TCG_MPC_UPLOAD=1 pytest workflows/tcg/tests/test_pokedex_proxies.py -k upload -v
"""
import json
import os
from pathlib import Path

import pytest

from workflows.tcg.tasks.pokedex_proxies import (
    OUTPUT_DIR,
    build_order_xmls,
    build_pokedex,
    darken,
    fetch_printings,
    parse_pokedex_html,
    pick_preview_dex_numbers,
    render_cards,
    run_pokedex_proxy_pipeline,
    slugify,
    sort_printings,
    tier_of,
    upload_to_mpc,
)


# ── Workflow (integration) ────────────────────────────────────────────────────

def test__build_pokedex():
    result = build_pokedex()
    assert "dex entries" in result
    entries = json.loads((OUTPUT_DIR / "pokedex.json").read_text(encoding="utf-8"))
    assert len(entries) >= 1000
    assert entries[0] == {"dex_number": 1, "name": "Bulbasaur",
                          "types": ["Grass", "Poison"]}
    # Forms must be deduped — one entry per dex number.
    numbers = [e["dex_number"] for e in entries]
    assert len(numbers) == len(set(numbers))


def test__fetch_printings_subset():
    """Charizard (heavy) + Caterpie (likely sparse) through the live API."""
    build_pokedex()
    result = fetch_printings(dex_numbers=[6, 10])
    assert "failure" in result
    cached = json.loads((OUTPUT_DIR / "printings.json").read_text(encoding="utf-8"))
    assert "6" in cached
    charizard = cached["6"]
    assert any(p["rarity"] == "Special Illustration Rare" for p in charizard)
    # Tier-1 entries must precede tier-2; newest-first within tier.
    tiers = [p["tier"] for p in charizard]
    assert tiers == sorted(tiers)


def test__render_cards_preview():
    """The visual sign-off artifact: ~10 samples incl. Charizard + no-prints."""
    build_pokedex()
    fetch_printings(dex_numbers=[1, 6, 10, 13, 25, 150, 151])
    result = render_cards(preview=True)
    assert "rendered" in result
    preview_dir = OUTPUT_DIR / "preview"
    rendered = list(preview_dir.glob("*.png"))
    assert any(p.name.startswith("0006-") for p in rendered), "Charizard sample missing"
    assert (OUTPUT_DIR / "cardback.png").is_file()
    # MPC bleed spec — every render must be exactly 822x1122.
    import struct
    head = rendered[0].read_bytes()[:24]
    width, height = struct.unpack(">II", head[16:24])
    assert (width, height) == (822, 1122)


def test__build_order_xmls_from_preview(tmp_path):
    """Order building on a copied preview set (isolated output dir)."""
    src = OUTPUT_DIR / "preview"
    if not src.is_dir() or not list(src.glob("*.png")):
        pytest.skip("run test__render_cards_preview first")
    import shutil
    out = tmp_path / "output"
    (out / "cards").mkdir(parents=True)
    for p in src.glob("*.png"):
        shutil.copy(p, out / "cards" / p.name)
    shutil.copy(OUTPUT_DIR / "cardback.png", out / "cardback.png")
    result = build_order_xmls(output_dir=str(out))
    assert "OK" in result and "PROBLEMS" not in result


@pytest.mark.skipif(os.environ.get("TCG_FULL_PIPELINE") != "1",
                    reason="Manual full run — ~1025 API calls + ~1025 renders "
                           "(set TCG_FULL_PIPELINE=1)")
def test__run_pokedex_proxy_pipeline_full():
    """THE full-flow trigger: dex → printings → all cards → order XMLs."""
    result = run_pokedex_proxy_pipeline(preview=False, upload=False)
    assert "order(s)" in result
    xmls = sorted(OUTPUT_DIR.glob("pokedex_proxies_*.xml"))
    assert len(xmls) == 2   # ~1025 cards split across two ≤612 projects


@pytest.mark.skipif(os.environ.get("TCG_MPC_UPLOAD") != "1",
                    reason="Manual only — drives a headed browser against the "
                           "real MPC account and saves projects "
                           "(set TCG_MPC_UPLOAD=1)")
def test__upload_to_mpc():
    result = upload_to_mpc()
    assert "saved" in result


def test__run_pipeline_preview_mode():
    """Orchestrator in default (preview) mode stops before orders/MPC."""
    result = run_pokedex_proxy_pipeline(preview=True)
    assert "PREVIEW ONLY" in result


# ── Unit / function ───────────────────────────────────────────────────────────

def test__slugify_handles_special_names():
    assert slugify("Farfetch'd") == "farfetchd"
    assert slugify("Mr. Mime") == "mr-mime"
    assert slugify("Nidoran♀") == "nidoran"
    assert slugify("Flabébé") == "flabebe"


def test__darken_returns_hex():
    assert darken("#EE8130") == "#9a531f"


def test__tier_of_mapping():
    assert tier_of("Special Illustration Rare") == 1
    assert tier_of("Illustration Rare") == 1
    assert tier_of("Rare Holo Star") == 2
    assert tier_of("Promo") == 2
    assert tier_of("Common") is None
    assert tier_of(None) is None


def test__sort_printings_tiers_then_newest():
    rows = [
        {"tier": 2, "release_date": "2024/01/26", "set_name": "Paldean Fates"},
        {"tier": 1, "release_date": "2023/08/11", "set_name": "Obsidian Flames"},
        {"tier": 1, "release_date": "2025/11/14", "set_name": "Phantasmal Flames"},
        {"tier": 2, "release_date": "", "set_name": "Unknown"},
    ]
    ordered = sort_printings(rows)
    assert [r["set_name"] for r in ordered] == [
        "Phantasmal Flames", "Obsidian Flames", "Paldean Fates", "Unknown"]


def test__parse_pokedex_html_dedupes_forms():
    html = """
    <table id="pokedex"><tbody>
      <tr><td>6</td><td><a class="ent-name">Charizard</a></td>
          <td><a>Fire</a> <a>Flying</a></td></tr>
      <tr><td>6</td><td><a class="ent-name">Charizard</a>
          <small>Mega Charizard X</small></td><td><a>Fire</a> <a>Dragon</a></td></tr>
      <tr><td>7</td><td><a class="ent-name">Squirtle</a></td><td><a>Water</a></td></tr>
    </tbody></table>"""
    entries = parse_pokedex_html(html)
    assert entries == [
        {"dex_number": 6, "name": "Charizard", "types": ["Fire", "Flying"]},
        {"dex_number": 7, "name": "Squirtle", "types": ["Water"]},
    ]


def test__pick_preview_dex_numbers_includes_heavy_and_empty():
    printings = {"6": [{"tier": 1}] * 30, "25": [{"tier": 1}] * 5,
                 "10": [], "1": [{"tier": 1}], "150": [{"tier": 1}],
                 "151": [{"tier": 1}], "13": []}
    preview = pick_preview_dex_numbers(printings, sample_size=6)
    assert 6 in preview          # the heavy case
    assert 10 in preview or 13 in preview   # a no-prints case
    assert len(preview) == 6
