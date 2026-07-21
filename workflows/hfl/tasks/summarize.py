"""
workflows/hfl/tasks/summarize.py

Weekly rollup of HFL entries — Haiku 4.5 by default. Emits a Markdown
summary alongside the per-day corpus files (`hfl/YYYY-Www-rollup.md`).

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

from workflows.hfl.dto import HflEntry
from workflows.hfl.es_store import index_hfl_entry
from workflows.hfl.prompts import load_prompt
from workflows.hfl.references import resolve_references as _resolve_references
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


def _rollup_tags(
    entries: list[dict[str, str]], iso_year: int, iso_week: int
) -> tuple[str, ...]:
    """Return stable rollup tags plus every tag present in source entries."""
    source_tags = {
        tag
        for entry in entries
        for tag in HflEntry.from_markdown(entry["header"], entry["body"]).tags
    }
    base_tags = ("weekly", "summary", f"{iso_year}-W{iso_week:02d}")
    return (*base_tags, *(tag for tag in sorted(source_tags) if tag not in base_tags))


def _rollup_filename(iso_year: int, iso_week: int) -> str:
    return f"{iso_year}-W{iso_week:02d}-rollup.md"


def _render_rollup(
    summary_text: str,
    entries: list[dict[str, str]],
    files: list[Path],
    *,
    window_days: int,
    iso_year: int,
    iso_week: int,
) -> str:
    tags = " ".join(f"#{tag}" for tag in _rollup_tags(entries, iso_year, iso_week))
    return (
        f"# Weekly rollup — {iso_year}-W{iso_week:02d}\n"
        f"Window: last {window_days} days · "
        f"{entries[0]['date']} → {entries[-1]['date']} · "
        f"{len(entries)} entries across {len(files)} files\n\n"
        f"{summary_text}\n\n"
        f"## Tags\n"
        f"Tags: {tags}\n\n"
    )


def _build_reference_appendix(
    entries: list[dict[str, str]],
    *,
    timeout: float,
    max_bytes: int,
    max_total: int,
) -> tuple[str, int, int]:
    """Resolve every entry's references into a bounded prompt appendix.

    Returns (appendix_text, resolved_ok, refs_seen). The appendix is empty
    when no entry carries references. Unresolved references are still
    listed (annotated) so the model knows the source existed.
    """
    blocks: list[str] = []
    refs_seen = 0
    resolved_ok = 0
    for e in entries:
        entry = HflEntry.from_markdown(e["header"], e["body"])
        if not entry.references:
            continue
        refs_seen += len(entry.references)
        results = _resolve_references(
            entry.references,
            timeout=timeout, max_bytes=max_bytes, max_total=max_total,
        )
        lines = [f'For entry "{e["date"]} — {e["header"]}":']
        for r in results:
            if r["ok"] and r["content"]:
                resolved_ok += 1
                lines.append(f'  [{r["ref"]}] ({r["reason"]})')
                lines.append(f'  """{r["content"]}"""')
            else:
                lines.append(f'  [{r["ref"]}] (unresolved: {r["reason"]})')
        blocks.append("\n".join(lines))
    if not blocks:
        return "", 0, 0
    appendix = (
        "\n\nReferenced material (resolved from entry references — use it "
        "to ground the summary; do not quote verbatim):\n\n"
        + "\n\n".join(blocks)
    )
    return appendix, resolved_ok, refs_seen


@SPROUT.task()
@log_result()
def summarize_hfl_week(
    *,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    window_days: int = 7,
    max_tokens: int = 1024,
    resolve_references: bool = True,
    ref_timeout: float = 10.0,
    ref_max_bytes: int = 20_000,
    ref_max_total: int = 60_000,
) -> dict[str, Any]:
    """Generate a weekly rollup of the last `window_days` of HFL entries.

    When `resolve_references` is True, each entry's `References:` are
    fetched (bounded by ref_timeout / ref_max_bytes / ref_max_total) and
    the resolved excerpts are appended to the prompt so the summary is
    grounded in the source material, not just the one-line moments.

    Returns:
        {"summary_path": str, "entries_seen": int, "files_seen": int,
         "model": str, "references_seen": int, "references_resolved": int}
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

    appendix, refs_ok, refs_seen = ("", 0, 0)
    if resolve_references:
        try:
            appendix, refs_ok, refs_seen = _build_reference_appendix(
                entries, timeout=ref_timeout,
                max_bytes=ref_max_bytes, max_total=ref_max_total,
            )
        except Exception as exc:  # noqa: BLE001 - references must not break the rollup
            _log.warning("hfl.summarize: reference resolution failed (%s)", exc)
            appendix, refs_ok, refs_seen = ("", 0, 0)

    user_msg = (
        f"Window: last {window_days} days "
        f"({entries[0]['date']} → {entries[-1]['date']}).\n\n"
        f"Entries:\n\n{_format_for_prompt(entries)}"
        f"{appendix}"
    )

    client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id__anthropic))
    if not client.base_client:
        raise RuntimeError("Anthropic client failed to initialize")

    # Public send_messages() wrapper: backoff retries AND the Max -> API
    # provider fallback on rate-limit/quota. Calling _with_backoff directly
    # would retry the throttled provider only.
    response = client.send_messages(
        messages=[{"role": "user", "content": user_msg}],
        model=model,
        max_tokens=max_tokens,
        system=_SYSTEM_PROMPT,
    )
    summary_text = response.content[0].text.strip() if response.content else ""

    now = datetime.now()
    iso_year, iso_week, _ = now.isocalendar()
    corpus_dir = resolve_corpus_dir()
    out_path = corpus_dir / _rollup_filename(iso_year, iso_week)
    out_path.write_text(
        _render_rollup(
            summary_text,
            entries,
            files,
            window_days=window_days,
            iso_year=iso_year,
            iso_week=iso_week,
        ),
        encoding="utf-8",
    )

    # Dual-write the rollup as one synthesized entry so the weekly view is
    # queryable via the memory_recall_es MCP alongside the per-day entries
    # (manifesto: summarize's express_target is file:hfl_summary+es_log).
    # Best-effort — the file write above is the source of truth.
    index_hfl_entry(
        HflEntry(
            when=now,
            moment=f"Weekly rollup — {iso_year}-W{iso_week:02d}",
            what_happened=summary_text,
            why_it_stayed=(
                f"Rollup of {len(entries)} entries across {len(files)} "
                f"files ({entries[0]['date']} → {entries[-1]['date']})."
            ),
            possible_use="weekly-review",
            tags=_rollup_tags(entries, iso_year, iso_week),
        ),
        source="summarize",
        synthesized=True,
    )

    return {
        "summary_path": str(out_path),
        "entries_seen": len(entries),
        "files_seen": len(files),
        "model": model,
        "references_seen": refs_seen,
        "references_resolved": refs_ok,
    }
