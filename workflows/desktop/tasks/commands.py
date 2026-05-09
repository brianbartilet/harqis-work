import os, subprocess, sys, tomllib
from pathlib import Path

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.files import copy_files_any
from apps.rainmeter.references.helpers.settings import set_rainmeter_always_on_top
from apps.rainmeter.references.helpers.config_builder import _refresh_app
from apps.desktop.helpers.feed import feed

from apps.apps_config import CONFIG_MANAGER

# Repo root resolved at import time — workflows/desktop/tasks/commands.py → 4 parents up.
REPO_ROOT = Path(__file__).resolve().parents[3]


@log_result()
@SPROUT.task()
def git_pull_on_paths() -> str:

    def git_pull_all(paths: list[str]) -> dict:
        """
        Runs `git pull` for each path in the list.

        Args:
            paths (list[str]): List of local git repo directories.

        Returns:
            dict: {path: (success: bool, output: str)}
        """
        results = {}

        for path in paths:
            if not os.path.isdir(path):
                results[path] = (False, "Path not found")
                continue

            try:
                # Run git pull inside the directory
                result = subprocess.run(
                    ["git", "pull"],
                    cwd=path,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )

                success = result.returncode == 0
                output = result.stdout if success else result.stderr

                results[path] = (success, output)

                print(f"\n=== {path} ===")
                print(output)

            except Exception as e:
                results[path] = (False, str(e))
                print(f"\nError pulling {path}: {e}")

        return results

    pull_list = [str(REPO_ROOT)]

    git_pull_all(pull_list)

    return " ".join(pull_list)


@log_result()
@feed()
@SPROUT.task()
def copy_files_targeted(**kwargs) -> str:
    cfg = CONFIG_MANAGER.get(kwargs.get("cfg_id__desktop_jobs", "DESKTOP"))
    p_from = Path(cfg['copy_files']['path_dev_files'])
    p_to = Path(cfg['copy_files']['path_run_files'])

    # Source the file list from machines.local.toml [sync] items so sensitive
    # paths live in one gitignored place instead of being hard-coded here.
    with open(p_from / "machines.local.toml", "rb") as f:
        items = tomllib.load(f).get("sync", {}).get("items", [])

    pairs: list[tuple[str, str]] = []
    for item in items:
        src = p_from / item
        if src.is_dir():
            for child in src.rglob("*"):
                if child.is_file():
                    rel = child.relative_to(p_from)
                    pairs.append((str(child), str(p_to / rel.parent)))
        else:
            pairs.append((str(src), str(p_to / Path(item).parent)))

    copy_files_any(pairs)

    return " ".join(p[0] for p in pairs)


@log_result()
@feed()
@SPROUT.task()
def set_desktop_hud_to_back() -> str:
    # Resolve %APPDATA%\Rainmeter\Rainmeter.ini
    rainmeter_ini = Path(os.environ["APPDATA"]) / "Rainmeter" / "Rainmeter.ini"
    set_rainmeter_always_on_top(str(rainmeter_ini))
    _refresh_app()

    return str(rainmeter_ini)


@log_result()
@feed()
@SPROUT.task()
def run_n8n_sequence() -> str:
    """Run the n8n backup → restore sequence using the platform-appropriate
    script in workflows/n8n/deploy/ (.bat on Windows, .sh on macOS/Linux)."""

    is_windows = sys.platform == "win32"
    ext = ".bat" if is_windows else ".sh"
    runner = ["cmd", "/c"] if is_windows else ["bash"]

    deploy_dir = REPO_ROOT / "workflows" / "n8n" / "deploy"
    scripts = [deploy_dir / f"backup{ext}", deploy_dir / f"restore{ext}"]

    results: dict[str, tuple[bool, str]] = {}
    for script in scripts:
        path = str(script)
        if not script.is_file():
            msg = f"script not found: {path}"
            results[path] = (False, msg)
            print(f"\n=== {path} ===\n{msg}")
            continue

        try:
            result = subprocess.run(
                [*runner, path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            success = result.returncode == 0
            output = result.stdout if success else result.stderr
            results[path] = (success, output)
            print(f"\n=== {path} (exit={result.returncode}) ===\n{output}")
        except Exception as e:
            results[path] = (False, str(e))
            print(f"\nError running {path}: {e}")

    return " | ".join(str(s) for s in scripts)


