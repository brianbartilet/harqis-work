import os, subprocess, sys, tomllib
from datetime import datetime
from pathlib import Path

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.files import copy_files_any
from apps.rainmeter.references.helpers.settings import set_rainmeter_always_on_top
from apps.rainmeter.references.helpers.config_builder import _refresh_app
from apps.desktop.helpers.feed import feed

from apps.apps_config import CONFIG_MANAGER
from workflows.dumps.config import load_merged_config, resolve_local_machine_name

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
def copy_files_targeted(cfg_id__desktop_jobs: str | None = None, **kwargs) -> str:
    cfg = CONFIG_MANAGER.get(cfg_id__desktop_jobs or kwargs.get("cfg_id__desktop_jobs", "DESKTOP"))
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
    # Resolve %APPDATA%\Rainmeter\Rainmeter.ini. APPDATA only exists in an
    # interactive Windows session — a worker launched as a service / scheduled
    # task may not inherit it, so skip cleanly instead of raising KeyError
    # (which logged this task as failing on nearly every run).
    appdata = os.environ.get("APPDATA")
    if not appdata:
        msg = "skipped: APPDATA not set (non-interactive Windows env)"
        print(msg)
        return msg
    rainmeter_ini = Path(appdata) / "Rainmeter" / "Rainmeter.ini"
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


# ── Auto-push: fanout across workers, each commits + pushes its local paths ──

def _git(args: list[str], cwd: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run git with terminal prompts disabled so creds-missing fails fast."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, timeout=timeout,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def _push_one_repo(path: str) -> tuple[str, str]:
    """Add+commit+push one repo. Returns (status, detail).

    status: 'pushed' | 'no-changes' | 'skipped' | 'error'.
    Never raises — the daily broadcast must not die on one bad path.
    """
    p = Path(path)
    if not p.is_dir() or not (p / ".git").exists():
        return "skipped", "not a git repo"

    try:
        # 1. Stage every working-tree change (tracked + untracked).
        _git(["add", "-A"], cwd=path)

        # 2. Anything to commit?
        staged = _git(["diff", "--cached", "--name-only"], cwd=path)
        has_staged = bool(staged.stdout.strip())

        if has_staged:
            stat = _git(["diff", "--cached", "--shortstat"], cwd=path).stdout.strip()
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            msg = f"chore(auto): sync {stamp} — {stat}" if stat else f"chore(auto): sync {stamp}"
            c = _git(["commit", "-m", msg], cwd=path)
            if c.returncode != 0:
                return "error", f"commit failed: {(c.stderr or c.stdout).strip()[:200]}"

        # 3. Anything to push? (covers the case where commit ran AND the case
        #    where local was already ahead of upstream from a prior failed run.)
        ahead = _git(
            ["rev-list", "--count", "@{upstream}..HEAD"], cwd=path
        )
        if ahead.returncode != 0 or ahead.stdout.strip() == "0":
            return ("no-changes", "nothing to push") if not has_staged else ("pushed", "committed but no upstream delta")

        # 4. Push. On non-fast-forward, sync via rebase, abort cleanly on conflict.
        push = _git(["push"], cwd=path)
        if push.returncode == 0:
            return "pushed", msg if has_staged else "pushed prior local commits"

        stderr = (push.stderr or "").lower()
        if "non-fast-forward" in stderr or "fetch first" in stderr or "rejected" in stderr:
            pull = _git(["pull", "--rebase", "--autostash"], cwd=path, timeout=120)
            if pull.returncode != 0:
                # Conflicts: abort so the tree is left clean for the next run.
                _git(["rebase", "--abort"], cwd=path)
                return "error", f"rebase conflicted — aborted; manual resolve needed: {pull.stderr.strip()[:200]}"
            push2 = _git(["push"], cwd=path)
            if push2.returncode == 0:
                return "pushed", "rebased and pushed"
            return "error", f"push after rebase failed: {push2.stderr.strip()[:200]}"

        return "error", f"push failed: {push.stderr.strip()[:200]}"
    except subprocess.TimeoutExpired as exc:
        return "error", f"timeout running {' '.join(exc.cmd)}"
    except Exception as exc:  # noqa: BLE001 — broadcast must keep iterating
        return "error", f"unexpected: {exc!r}"


def _resolve_auto_push_paths() -> list[str]:
    """Read this machine's git_autopush.paths from machines.local.toml."""
    cfg = load_merged_config()
    machine = resolve_local_machine_name(cfg)
    block = (cfg.get(machine, {}) or {}).get("git_autopush", {}) or {}
    return [str(p) for p in (block.get("paths") or [])]


@log_result()
@SPROUT.task()
def git_auto_push_paths() -> str:
    """Broadcast: each worker iterates its own `[<machine>.git_autopush].paths`
    from machines.local.toml, stages+commits+pushes each repo. Missing/non-git
    paths are skipped. Push rejections trigger a `pull --rebase --autostash`
    and a single retry; conflicts abort cleanly and surface as 'error'.

    Returns a one-line summary per path (`<path>: <status> — <detail>`).
    """
    paths = _resolve_auto_push_paths()
    if not paths:
        return "no paths configured"

    lines: list[str] = []
    for path in paths:
        status, detail = _push_one_repo(path)
        lines.append(f"{path}: {status} — {detail}")
        print(f"\n=== {path} ===\n{status}: {detail}")
    return " | ".join(lines)


