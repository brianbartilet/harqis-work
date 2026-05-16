"""
workflows/hfl/tasks/summarize.py

Weekly rollup of HFL entries — Haiku 4.5 by default. Emits a Markdown
summary alongside the per-day corpus files (`hfl/_summary-YYYY-Www.md`).

Cost note: pass `model="claude-haiku-4-5-20251001"` from the beat schedule
(already the default in tasks_config). Do NOT raise it via the Anthropic
config default — that is shared by Sonnet-class workflows.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic

from workflows.hfl.prompts import load_prompt
from workflows.hfl.tasks.capture import resolve_corpus_dir
from workflows.hfl.tasks.retrieve import _entries_for_file

_log = create_logger("hfl.summarize")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"

# Prompt lives in the prompts/ layer as a .md file (repo convention — see
# workflows/<category>/prompts/). .strip() keeps the value byte-identical
# to the former inline string regardless of the file's trailing newline.
_SYSTEM_PROMPT = load_prompt("summarize_week").strip()


def _collect_window(window_days: int) -> tuple[list[dict[str, str]], list[Path]]:
    corpus_dir = resolve_corpus_dir()
    if not corpus_dir.exists():
        return [], []

    cutoff = (datetime.now() - timedelta(days=window_days)).date()
    files = sorted(corpus_dir.glob("*.md"))
    selected: list[Path] = []
    entries: list[dict[str, str]] = []
    for f in files:
        try:
            d = datetime.strptime(f.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < cutoff:
            continue
        selected.append(f)
        for e in _entries_for_file(f):
            entries.append({"date": str(d), **e})
    return entries, selected


def _format_for_prompt(entries: list[dict[str, str]]) -> str:
    if not entries:
        return "(no entries in this window)"
    return "\n\n".join(
        f"### {e['date']} — {e['header']}\n{e['body']}" for e in entries
    )


@SPROUT.task()
@log_result()
def summarize_hfl_week(
    *,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    window_days: int = 7,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    """Generate a weekly rollup of the last `window_days` of HFL entries.

    Returns:
        {"summary_path": str, "entries_seen": int, "files_seen": int, "model": str}
    """
    entries, files = _collect_window(window_days)
    if not entries:
        _log.info("No HFL entries in the past %d days — skipping summary.", window_days)
        return {
            "summary_path": "",
            "entries_seen": 0,
            "files_seen": 0,
            "model": model,
            "skipped": "empty",
        }

    user_msg = (
        f"Window: last {window_days} days "
        f"({entries[0]['date']} → {entries[-1]['date']}).\n\n"
        f"Entries:\n\n{_format_for_prompt(entries)}"
    )

    client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id__anthropic))
    if not client.base_client:
        raise RuntimeError("Anthropic client failed to initialize")

    response = client._with_backoff(
        client.base_client.messages.create,
        model=model,
        max_tokens=max_tokens,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    summary_text = response.content[0].text.strip() if response.content else ""

    iso_year, iso_week, _ = datetime.now().isocalendar()
    corpus_dir = resolve_corpus_dir()
    out_path = corpus_dir / f"_summary-{iso_year}-W{iso_week:02d}.md"
    header = (
        f"# HFL weekly summary — {iso_year}-W{iso_week:02d}\n"
        f"Window: last {window_days} days · "
        f"{entries[0]['date']} → {entries[-1]['date']} · "
        f"{len(entries)} entries across {len(files)} files\n\n"
    )
    out_path.write_text(header + summary_text + "\n", encoding="utf-8")

    return {
        "summary_path": str(out_path),
        "entries_seen": len(entries),
        "files_seen": len(files),
        "model": model,
    }
