"""
workflows/testing/tasks/test_farm_email.py

Celery beat task — the *delivery* half of the BDD "test case farm".

``workflows/testing/tasks/test_farm.run_test_farm`` regenerates
``logs/BDD-TEST-FARM.md`` at 09:00 on weekdays but notifies no one. This task
runs a few minutes later, renders that already-current markdown to HTML, emails
it via ``GOOGLE_GMAIL_SEND`` and posts a Telegram completion notice — by
shelling out to ``scripts/agents/daily_test_farm_email.py`` in ``--skip-generate``
mode so there is **no** second (duplicate, costly) Claude generation pass.

Why shell out instead of importing the script:
  * The script is a self-contained CLI entrypoint that bootstraps the full
    HARQIS runtime env in its own process (``scripts/launch.setup_env``: .env,
    machine overrides, ``PATH_APP_CONFIG``) — running it as a subprocess gives
    that clean, isolated bootstrap for free.
  * ``scripts/`` is not an importable package (no ``__init__.py``), so a direct
    ``from scripts.agents... import`` is not reliable from the worker.
  * It keeps a single source of truth for the render → Gmail → Telegram path and
    mirrors the pattern ``run_test_farm`` already uses to shell out to ``claude``.

Pinned (via the beat entry) to the same ``peon`` / windows host as
``run_test_farm`` so it shares the ``GOOGLE_GMAIL_SEND`` + ``TELEGRAM`` configs
and reads the markdown that host just produced.

References:
- workflows/testing/tasks/test_farm.py — the generation half (run at 09:00).
- scripts/agents/daily_test_farm_email.py — the render/email/telegram sequence.
"""
import sys
import subprocess
from pathlib import Path

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

_log = create_logger("testing.test_farm_email")

# __file__ = repo/workflows/testing/tasks/test_farm_email.py → parents[3] = root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_EMAIL_SCRIPT = _REPO_ROOT / "scripts" / "agents" / "daily_test_farm_email.py"

# Render + Gmail send + Telegram post; comfortably above a normal run.
_DEFAULT_TIMEOUT: int = 300


@log_result()
@SPROUT.task()
def send_test_farm_report(**kwargs):
    """Render ``logs/BDD-TEST-FARM.md`` and deliver it by email + Telegram.

    Delegates to ``scripts/agents/daily_test_farm_email.py`` — the single source
    of truth for the render → Gmail → Telegram sequence — so this task never
    triggers a second Claude generation pass.

    Kwargs:
        skip_generate: Reuse the existing markdown that ``run_test_farm`` already
                       produced (default True). Set False only to let the script
                       refresh the farm itself first — this duplicates the 09:00
                       ``run_test_farm`` generation and is rarely wanted.
        dry_run:       Render artifacts but do not send (default False).
        timeout:       Seconds allowed for the script (default 300).
        extra_args:    Optional list of extra CLI flags forwarded verbatim
                       (e.g. ['--no-telegram'] or ['--to', 'a@b.com']).

    Returns:
        The script's delivery summary (stdout). Raises on non-zero exit so the
        failure is captured by ``@log_result`` and surfaced in the worker log.
    """
    if not _EMAIL_SCRIPT.exists():
        raise RuntimeError(f"test farm email script missing: {_EMAIL_SCRIPT}")

    skip_generate = kwargs.get("skip_generate", True)
    dry_run = bool(kwargs.get("dry_run", False))
    timeout = int(kwargs.get("timeout", _DEFAULT_TIMEOUT))

    cmd = [sys.executable, str(_EMAIL_SCRIPT)]
    if skip_generate:
        # No generation needed → also skip the (now-irrelevant) Claude auth probe.
        cmd += ["--skip-generate", "--no-claude-preflight"]
    if dry_run:
        cmd.append("--dry-run")
    cmd += list(kwargs.get("extra_args") or [])

    _log.info("test_farm_email: delivering report — %s", " ".join(cmd[1:]))
    proc = subprocess.run(
        cmd, cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"daily_test_farm_email exited {proc.returncode}: "
            f"{(proc.stderr or proc.stdout or '').strip()[:800]}"
        )

    summary = (proc.stdout or "").strip()
    _log.info("test_farm_email: delivered — %s",
              summary.splitlines()[-1] if summary else "(no output)")
    return summary or "test farm report delivered"
