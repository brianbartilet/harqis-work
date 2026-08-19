import ast
from collections import Counter
from pathlib import Path


def test_workflow_hfl_declares_each_beat_key_once():
    source_path = Path(__file__).parents[1] / "tasks_config.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    workflow = next(
        node.value
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "WORKFLOW_HFL"
            for target in node.targets
        )
    )
    keys = [
        key.value
        for key in workflow.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    ]
    duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)

    assert duplicates == []
