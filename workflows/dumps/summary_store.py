"""
workflows/dumps/summary_store.py

Per-day Markdown sink for the daily-dumps analyzer — mirrors the HFL corpus
pattern (workflows/hfl/tasks/capture.py: one file per day, idempotent).

`analyze_daily_dumps` already pushes a rendered summary to the HUD feed
(`@feed()` → shared `hud-logs-YYYYMMDD.txt`) and the structured return to ES
(`@log_result()`). Neither is a clean, standalone per-day record: the feed is a
`.txt` shared with every other HUD task, newest-first, and ES isn't a file you
can open. This module adds a dedicated Markdown artifact — `<dir>/YYYY-MM-DD.md`
— written for each scanned day. It is *additive*: the feed + ES paths are
untouched, exactly as HFL keeps both its corpus and its ES projection.

Two sinks, written in parallel (the operator asked for "both"):
  A. Repo sink   — machines.local.toml `[dumps] summary_path` → apps_config
                   DUMPS.summary.path → DUMPS_SUMMARY_PATH env → <repo>/logs/
                   dumps/. Always created.
  B. Feed sink   — <resolved-feed-dir>/dumps/ when the feed dir already exists
                   on this host (so the file rides the same Drive sync as the
                   HUD feed and is readable from any machine). Skipped cleanly
                   when no feed dir is configured/mounted here — same foreign-OS
                   safety rule @feed() uses.

Writes are idempotent overwrites: a closed day's dumps are final, so re-running
the retro for a date rewrites that one file rather than stacking duplicates
(unlike the prepend-blob feed). Each write is atomic (temp + os.replace) so a
Drive-synced reader never sees a half-written file.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path

from core.utilities.logging.custom_logger import create_logger

_log = create_logger("dumps.summary_store")

REPO_ROOT = Path(__file__).resolve().parents[2]


def _human_bytes(n: int) -> str:
    """Byte count → human string. Mirrors analyze._human_bytes (kept local so
    this module never imports the task — analyze imports *this* one)."""
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{int(f)} B" if unit == "B" else f"{f:.1f} {unit}"
        f /= 1024
    return f"{f:.1f} PB"


def _repo_sink() -> Path:
    """Resolve the primary (host-local) summary dir. Always returned; created
    on write.

    Precedence (first hit wins):
      1. machines.local.toml `[dumps] summary_path` — the canonical home, right
         next to `harqis_server_inbox` (both are host-local to harqis-server).
      2. apps_config `DUMPS.summary.path`.
      3. env `DUMPS_SUMMARY_PATH`.
      4. `<repo>/logs/dumps/` (fallback).
    """
    try:
        from workflows.dumps.config import get_dumps_summary_path
        toml_path = get_dumps_summary_path()
        if toml_path and "${" not in toml_path:
            return Path(toml_path).expanduser().resolve()
    except Exception:
        pass

    try:
        from apps.apps_config import CONFIG_MANAGER
        dumps_cfg = CONFIG_MANAGER.get("DUMPS")
        if dumps_cfg and isinstance(dumps_cfg, dict):
            cfg_path = (dumps_cfg.get("summary") or {}).get("path")
            if cfg_path and "${" not in cfg_path:
                return Path(cfg_path).expanduser().resolve()
    except Exception:
        pass

    env_path = os.environ.get("DUMPS_SUMMARY_PATH", "").strip()
    if env_path:
        return Path(env_path).expanduser().resolve()

    return (REPO_ROOT / "logs" / "dumps").resolve()


def _feed_sink() -> Path | None:
    """Resolve `<feed-dir>/dumps/` when the feed dir exists on this host.

    Reuses the feed module's own OS-aware resolver so the dumps summaries land
    next to the HUD feed and ride the same Drive sync. Returns None when no
    feed dir is configured or it isn't a directory here (foreign-OS path,
    unmounted drive, host with no feed sink) — same skip rule as @feed().
    """
    try:
        from apps.desktop.helpers.feed import _resolve_feed_path
        raw = _resolve_feed_path()
    except Exception:
        return None
    if not raw or "${" in raw:
        return None
    base = Path(raw)
    if not base.is_dir():
        return None
    return (base.resolve() / "dumps")


def resolve_summary_dirs() -> list[Path]:
    """Return the de-duplicated list of dirs a day's summary is written to.

    Always includes the repo sink; includes the feed sink when it resolves on
    this host. De-duplicated so a config that points both at the same place
    only writes once.
    """
    dirs: list[Path] = [_repo_sink()]
    feed = _feed_sink()
    if feed is not None:
        dirs.append(feed)

    seen: set[str] = set()
    unique: list[Path] = []
    for d in dirs:
        key = str(d)
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique


def render_day_markdown(
    date_suffix: str,
    machines: list[dict],
    inbox_path: str,
    *,
    now: datetime | None = None,
) -> str:
    """Render one day's per-machine dump stats as a standalone Markdown doc."""
    stamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    if not machines:
        return (
            f"# Daily Dumps — {date_suffix}\n\n"
            f"_No machine dumps found._\n\n"
            f"_Generated {stamp} · inbox `{inbox_path}`_\n"
        )

    files_total = sum(m["files_count"] for m in machines)
    bytes_total = sum(m["bytes_total"] for m in machines)
    by_bytes = sorted(machines, key=lambda m: m["bytes_total"], reverse=True)

    lines = [
        f"# Daily Dumps — {date_suffix}",
        "",
        f"{len(machines)} machine(s) · {files_total} files · "
        f"{_human_bytes(bytes_total)}",
        "",
        "| machine | files | bytes |",
        "|---|---|---|",
    ]
    for m in by_bytes:
        lines.append(
            f"| {m['machine']} | {m['files_count']} | "
            f"{_human_bytes(m['bytes_total'])} |"
        )
    lines += ["", f"_Generated {stamp} · inbox `{inbox_path}`_", ""]
    return "\n".join(lines)


def _atomic_write(path: Path, text: str) -> None:
    """Write `text` to `path` atomically (temp file + os.replace).

    Atomic replace matters for the Drive-synced feed sink: a syncing reader
    never observes a partially-written file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", delete=False, dir=str(path.parent), encoding="utf-8",
    ) as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)


def write_day_summary(
    date_suffix: str,
    machines: list[dict],
    inbox_path: str,
    *,
    now: datetime | None = None,
) -> list[str]:
    """Write `<dir>/<date>.md` to every resolved sink. Idempotent overwrite.

    Best-effort per sink: a failure on one dir is logged and skipped so it
    never breaks the beat or starves the other sink. Returns the list of paths
    actually written.
    """
    text = render_day_markdown(date_suffix, machines, inbox_path, now=now)
    written: list[str] = []
    for d in resolve_summary_dirs():
        target = d / f"{date_suffix}.md"
        try:
            _atomic_write(target, text)
            written.append(str(target))
            _log.info("dumps: wrote day summary %s (%d machines)",
                      target, len(machines))
        except Exception as exc:  # noqa: BLE001 - one sink failing must not break others
            _log.warning("dumps: failed to write day summary %s (%s)", target, exc)
    return written
