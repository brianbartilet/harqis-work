"""Keep known unavailable probes opt-in without suppressing their assertions."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
QUARANTINED = [
    ("apps/pokemon_tcg/tests/test_cards.py", "test_search_cards"),
    ("apps/pokemon_tcg/tests/test_sets.py", "test_list_sets"),
    ("apps/google_apps/tests/test_tasks.py", "test_list_task_lists"),
    ("apps/youtube/tests/test_analytics.py", "test_get_channel_summary"),
]


def markers(path, name):
    # Avoid importing live API clients or initializing OAuth during this check.
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    return {ast.unparse(decorator).split("(", 1)[0] for decorator in function.decorator_list}


@pytest.mark.parametrize("path,name", QUARANTINED)
def test_quarantined_probe_is_manual_integration_not_daily_smoke(path, name):
    assert markers(path, name) == {"pytest.mark.integration"}


def test_other_pokemon_smoke_probe_remains_enabled():
    assert markers("apps/pokemon_tcg/tests/test_cards.py", "test_search_cards_by_dex_number") == {
        "pytest.mark.smoke"
    }
