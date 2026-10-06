"""
workflows/hfl/tasks/summarize.py

Weekly rollup of HFL entries — Haiku 4.5 by default. Emits a Markdown
summary alongside the per-day corpus files (`hfl/YYYY-Www-rollup.md`).

Cost note: pass `model="claude-haiku-4-5-20251001"` from the beat schedule
(already the default in tasks_config). Do NOT raise it via the Anthropic
config default — that is shared by Sonnet-class workflows.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
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
# Conservative UTF-8 ceiling including system text; not a token estimate.
_MAX_PROMPT_BYTES = 120_000

# Prompt lives in the prompts/ layer as a .md file (repo convention — see
# workflows/<category>/prompts/). .strip() keeps the value byte-identical
# to the former inline string regardless of the file's trailing newline.
_SYSTEM_PROMPT = load_prompt("summarize_week").strip()


def _collect_window(
    window_days: int, *, end_date: date | None = None,
) -> tuple[list[dict[str, str]], list[Path]]:
    if type(window_days) is not int or window_days < 1:
        raise ValueError("window_days must be a positive integer")
    end_date = end_date or datetime.now().date()
    cutoff = end_date - timedelta(days=window_days - 1)
    corpus_dir = resolve_corpus_dir()
    if not corpus_dir.exists():
        return [], []

    files = sorted(
        (p for p in corpus_dir.rglob("*.md")
         if not any(part.startswith(".") for part in p.relative_to(corpus_dir).parts)),
        key=lambda p: (p.stem, str(p)),
    )
    selected: list[Path] = []
    entries: list[dict[str, str]] = []
    for f in files:
        try:
            d = datetime.strptime(f.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if not cutoff <= d <= end_date:
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
    """Resolve references within one global UTF-8 appendix budget.

    Metadata and excerpts share max_total; stop fetching once it is spent.
    Returns (appendix_text, resolved_ok, refs_seen) for visited entries only.
    Excerpts may be truncated, explicitly disclosed in the appendix heading.
    """
    appendix = "\n\nReferenced material (bounded excerpts; may be incomplete):\n\n"
    if max_total <= len(appendix.encode("utf-8")):
        return "", 0, 0
    refs_seen = 0
    resolved_ok = 0
    for e in entries:
        remaining = max_total - len(appendix.encode("utf-8"))
        if remaining <= 0:
            break
        entry = HflEntry.from_markdown(e["header"], e["body"])
        if not entry.references:
            continue
        refs_seen += len(entry.references)
        results = _resolve_references(
            entry.references,
            timeout=timeout, max_bytes=min(max_bytes, remaining), max_total=remaining,
        )
        lines = [f'For entry "{e["date"]} — {e["header"]}":']
        for r in results:
            if r["ok"] and r["content"]:
                resolved_ok += 1
                lines.append(f'  [{r["ref"]}] ({r["reason"]})')
                lines.append(f'  """{r["content"]}"""')
            else:
                lines.append(f'  [{r["ref"]}] (unresolved: {r["reason"]})')
        block = "\n".join(lines) + "\n\n"
        appendix += block.encode("utf-8")[:remaining].decode("utf-8", errors="ignore")
        if len(block.encode("utf-8")) >= remaining:
            break
    if not refs_seen:
        return "", 0, 0
    return appendix, resolved_ok, refs_seen


@SPROUT.task()
@log_result()
def summarize_hfl_week(
    *,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    window_days: int = 7,
    end_date: str | None = None,
    max_tokens: int = 1024,
    resolve_references: bool = True,
    ref_timeout: float = 10.0,
    ref_max_bytes: int = 20_000,
    ref_max_total: int = 60_000,
) -> dict[str, Any]:
    """Generate a rollup of exactly `window_days` calendar days, inclusive.

    `end_date` is an optional YYYY-MM-DD in the worker's local calendar;
    it anchors both the input window and the output ISO-week identity.
    Archived daily files are included. The complete entry body is never
    silently sampled: oversized input fails before external work. System
    and user text share a conservative 120,000 UTF-8-byte ceiling.

    When `resolve_references` is True, fetched excerpts and metadata share
    one global ref_max_total budget, further capped by remaining prompt room.

    Returns:
        {"summary_path": str, "entries_seen": int, "files_seen": int,
         "model": str, "references_seen": int, "references_resolved": int}
    """
    now = datetime.now()
    end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date is not None else now.date()
    if end_date is not None and end.isoformat() != end_date:
        raise ValueError("end_date must be YYYY-MM-DD")
    entries, files = _collect_window(window_days, end_date=end)
    start = end - timedelta(days=window_days - 1)
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
        f"Window: {start.isoformat()} → {end.isoformat()} ({window_days} days).\n\n"
        f"Entries:\n\n{_format_for_prompt(entries)}"
    )
    base_bytes = len((_SYSTEM_PROMPT + user_msg).encode("utf-8"))
    if base_bytes > _MAX_PROMPT_BYTES:
        raise ValueError(
            f"weekly prompt exceeds byte budget: {base_bytes} > {_MAX_PROMPT_BYTES}; "
            "no references fetched or model called; reviewed chunked synthesis required"
        )
    appendix, refs_ok, refs_seen = ("", 0, 0)
    if resolve_references:
        try:
            appendix, refs_ok, refs_seen = _build_reference_appendix(
                entries, timeout=ref_timeout,
                max_bytes=ref_max_bytes,
                max_total=max(0, min(ref_max_total, _MAX_PROMPT_BYTES - base_bytes)),
            )
        except Exception as exc:  # noqa: BLE001 - references must not break the rollup
            _log.warning("hfl.summarize: reference resolution failed (%s)", exc)
            appendix, refs_ok, refs_seen = ("", 0, 0)

    user_msg += appendix

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

    iso_year, iso_week, _ = end.isocalendar()
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
            when=datetime.combine(end, datetime.min.time()) if end_date is not None else now,
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
        doc_id=f"hfl-weekly-{iso_year}-W{iso_week:02d}",
    )

    return {
        "summary_path": str(out_path),
        "entries_seen": len(entries),
        "files_seen": len(files),
        "model": model,
        "references_seen": refs_seen,
        "references_resolved": refs_ok,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "prompt_bytes": len((_SYSTEM_PROMPT + user_msg).encode("utf-8")),
    }
