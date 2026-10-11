"""Read-only scanner regression tests, without publisher/bootstrap imports."""
import ast
import logging
from pathlib import Path
import re


def load_scanner():
    # Execute the actual helper with its pure dependencies, not task decorators.
    root = Path(__file__).parents[4] / "workflows/dumps"
    namespace = {"Path": Path, "_log": logging.getLogger(__name__), "re": re}
    for file, names in [(root / "files.py", {"parse_dump_dir_name"}),
                        (root / "tasks/analyze.py", {"_scan_day"})]:
        tree = ast.parse(file.read_text(encoding="utf-8"))
        nodes: list[ast.stmt] = [n for n in tree.body if
            (isinstance(n, ast.FunctionDef) and n.name in names)
            or (isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_DUMP_DIR_RE" for t in n.targets))]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(file), "exec"), namespace)
    return namespace["_scan_day"]


def test_exact_device_skips_unrelated_trees_before_stat(tmp_path, monkeypatch):
    scan = load_scanner()
    day = "2026-10-10"
    selected = tmp_path / f"nothing-phone-daily-dumps-{day}"
    selected.mkdir()
    (selected / "sample").write_bytes(b"abc")
    for name in ["nothing-phone-pro", "desktop", "nothing"]:
        (tmp_path / f"{name}-daily-dumps-{day}").mkdir()
    original = Path.is_dir

    def guarded(path):
        if path.parent == tmp_path and path != selected:
            raise AssertionError("unrelated tree was touched")
        return original(path)

    monkeypatch.setattr(Path, "is_dir", guarded)
    assert scan(tmp_path, day, machine="nothing-phone") == [
        {"machine": "nothing-phone", "files_count": 1, "bytes_total": 3, "path": str(selected)}
    ]


def test_unfiltered_scan_preserves_counts_and_missing_day(tmp_path):
    scan = load_scanner()
    for name in ["nothing-phone", "desktop"]:
        folder = tmp_path / f"{name}-daily-dumps-2026-10-10"
        folder.mkdir()
        (folder / "sample").write_bytes(b"abc")
    all_stats = scan(tmp_path, "2026-10-10")
    assert len(all_stats) == 2
    assert scan(tmp_path, "2026-10-10", machine="nothing-phone") == [
        row for row in all_stats if row["machine"] == "nothing-phone"]
    assert scan(tmp_path, "2026-10-09", machine="nothing-phone") == []
    assert scan(tmp_path, "2026-10-10", machine="absent") == []


def test_task_passes_machine_filter_into_scan(tmp_path):
    from types import SimpleNamespace
    file = Path(__file__).parents[4] / "workflows/dumps/tasks/analyze.py"
    tree = ast.parse(file.read_text(encoding="utf-8"))
    task = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == "analyze_daily_dumps")
    task.decorator_list = []  # Never invoke feed/ES publishers in this test.
    calls = []
    def scan(inbox, day, machine=None):
        calls.append(machine)
        return []
    namespace = dict(Path=Path, _log=logging.getLogger(__name__),
        resolve_local_machine_name=lambda: "hub", HARQIS_SERVER_MACHINE_NAME="hub",
        get_dumps_target=lambda: SimpleNamespace(inbox=str(tmp_path)),
        _resolve_target_dates=lambda **kw: ["2026-10-10"], _scan_day=scan,
        _filter_machines=lambda rows, machine: rows,
        _render_gaps=lambda *args: "gap")
    exec(compile(ast.Module(body=[task], type_ignores=[]), str(file), "exec"), namespace)
    namespace["analyze_daily_dumps"](machine="nothing-phone", missing_only=True)
    assert calls == ["nothing-phone"]
