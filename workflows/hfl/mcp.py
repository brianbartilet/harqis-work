"""
workflows/hfl/mcp.py — "memory recall" MCP tools.

A read-only, time-period memory interface over the consolidated host store
on harqis-server (${HARQIS_DATA_ROOT}). Answers questions like:

  - "what was I working on last week?"
  - "generate an md file of what happened for the last 3 months"
  - "create a yearly summary from the months of 2025"
  - "what pictures were stored last week"

Tiered resolution (per the approved spec):
  T1 (always)        HFL corpus daily entries + _summary-*.md in window
  T2 (detail="full") + dumps media inventory + *.md/*.txt under the dumps
                       tree as supplementary context
  T3 (fallback only) if the corpus dir is missing/empty: best-effort scan
                       under ${HARQIS_DATA_ROOT} for media + *.md/*.txt

Narrative answers are synthesized with Claude Haiku (cost rule: never
raise the Anthropic DEFAULT_MODEL). If a window has no data, the tool
returns found=false with empty text and makes NO LLM call. No files are
written — markdown is returned as the tool result.

Runs inside mcp/server.py on harqis-server; reads /Volumes/harqis-data
paths directly. HFL_CORPUS_PATH / HARQIS_DATA_ROOT reach this process via
scripts/deploy.py start_service extra_env (machines.local.toml). Running
mcp/server.py directly (not via deploy.py) lacks those — resolve_corpus_dir
then falls back to <repo>/logs/hfl.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
from workflows.dumps.config import get_dumps_target
from workflows.dumps.files import iter_recent_files
from workflows.hfl.prompts import load_prompt
from workflows.hfl.tasks.capture import resolve_corpus_dir
from workflows.hfl.tasks.ingest_git import (
    collect_github_activity,
    distill_git_activity,
)
from workflows.hfl.tasks.retrieve import _entries_for_file, _parse_since

logger = logging.getLogger("harqis-mcp.memory")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"

# Kept local (not imported from analyze_media) so this module stays light —
# importing the vision task would pull opencv/anthropic for two constants.
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}

_MAX_SYNTH_CHARS = 60_000   # token guard for the Haiku context
_LONG_RANGE_DAYS = 45       # beyond this, prefer summaries over daily entries


def _today() -> date:
    return datetime.now().date()


def _data_root() -> Path:
    return Path(os.environ.get("HARQIS_DATA_ROOT", "").strip() or ".").expanduser()


# ── Window resolution ────────────────────────────────────────────────────────

def _resolve_window(
    period: str, since: str, until: str
) -> tuple[Optional[date], Optional[date], str]:
    """Return (start, end, label). Either bound may be None (unbounded)."""
    today = _today()
    p = (period or "").strip().lower()

    if p:
        named = {
            "last-week": 7, "last-month": 30, "last-3-months": 90,
            "last-quarter": 90, "last-6-months": 180, "last-year": 365,
        }
        if p in named:
            return today - timedelta(days=named[p] - 1), today, p
        if p == "ytd":
            return date(today.year, 1, 1), today, p
        m = re.fullmatch(r"last-(\d+)-days?", p)
        if m:
            n = max(1, int(m.group(1)))
            return today - timedelta(days=n - 1), today, p
        if re.fullmatch(r"\d{4}", p):
            y = int(p)
            return date(y, 1, 1), date(y, 12, 31), p
        m = re.fullmatch(r"(\d{4})-(\d{2})", p)
        if m:
            y, mo = int(m.group(1)), int(m.group(2))
            if 1 <= mo <= 12:
                start = date(y, mo, 1)
                end = (date(y + (mo == 12), (mo % 12) + 1, 1) - timedelta(days=1))
                return start, end, p
        m = re.fullmatch(r"(\d{4})-q([1-4])", p)
        if m:
            y, q = int(m.group(1)), int(m.group(2))
            start = date(y, 3 * (q - 1) + 1, 1)
            end_month = 3 * q
            end = date(y + (end_month == 12), (end_month % 12) + 1, 1) - timedelta(days=1)
            return start, end, p
        try:
            d = datetime.fromisoformat(p).date()
            return d, d, p
        except ValueError:
            logger.info("memory: unrecognized period %r — treating as unbounded", p)

    start = _parse_since(since) if since else None
    end = _parse_since(until) if until else today
    if start and end and start > end:
        start, end = end, start
    label = f"{start or 'beginning'}..{end or 'today'}"
    return start, end, label


def _in_window(d: date, start: Optional[date], end: Optional[date]) -> bool:
    if start and d < start:
        return False
    if end and d > end:
        return False
    return True


def _summary_overlaps(stem: str, start: Optional[date], end: Optional[date]) -> bool:
    """`_summary-YYYY-Www` — does its ISO week intersect [start, end]?"""
    m = re.search(r"(\d{4})-W(\d{1,2})", stem)
    if not m:
        return False
    try:
        wk_start = date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    except ValueError:
        return False
    wk_end = wk_start + timedelta(days=6)
    if start and wk_end < start:
        return False
    if end and wk_start > end:
        return False
    return True


# ── Collectors ───────────────────────────────────────────────────────────────

def _collect_corpus(
    corpus_dir: Path, start: Optional[date], end: Optional[date], query: str
) -> tuple[list[dict], list[dict]]:
    needle = query.strip().lower()
    entries: list[dict] = []
    summaries: list[dict] = []
    for f in sorted(corpus_dir.glob("*.md"), reverse=True):
        if f.stem.startswith("_summary"):
            if _summary_overlaps(f.stem, start, end):
                try:
                    text = f.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                if not needle or needle in text.lower():
                    summaries.append({"name": f.stem, "path": str(f), "text": text})
            continue
        try:
            fd = datetime.strptime(f.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if not _in_window(fd, start, end):
            continue
        for e in _entries_for_file(f):
            hay = f"{e['header']}\n{e['body']}".lower()
            if not needle or needle in hay:
                entries.append({
                    "date": str(fd), "header": e["header"],
                    "body": e["body"], "path": str(f),
                })
    return entries, summaries


def _window_dts(start: Optional[date], end: Optional[date]) -> tuple[datetime, datetime]:
    start_dt = datetime(start.year, start.month, start.day) if start else datetime(1970, 1, 1)
    end_d = (end or _today())
    end_dt = datetime(end_d.year, end_d.month, end_d.day) + timedelta(days=1)
    return start_dt, end_dt


def _collect_media(
    start: Optional[date], end: Optional[date], kinds: list[str], limit: int
) -> list[dict]:
    target = get_dumps_target()
    if not target:
        return []
    inbox = Path(target.inbox).expanduser()
    if not inbox.exists():
        return []
    want: set[str] = set()
    if "image" in kinds:
        want |= _IMAGE_EXTS
    if "video" in kinds:
        want |= _VIDEO_EXTS
    start_dt, end_dt = _window_dts(start, end)
    out: list[dict] = []
    for cf in iter_recent_files([inbox], start_dt, end_dt):
        suffix = cf.path.suffix.lower()
        if suffix not in want:
            continue
        parts = cf.relative.parts
        try:
            size = cf.path.stat().st_size
        except OSError:
            size = 0
        out.append({
            "name": cf.path.name,
            "path": str(cf.path),
            "machine": parts[0] if len(parts) > 1 else "",
            "kind": "video" if suffix in _VIDEO_EXTS else "image",
            "mtime": cf.mtime.strftime("%Y-%m-%d %H:%M"),
            "bytes": size,
        })
    out.sort(key=lambda m: m["mtime"], reverse=True)
    return out[:limit]


def _collect_dumps_text(
    start: Optional[date], end: Optional[date], query: str, limit: int
) -> list[dict]:
    """T2 supplement: *.md / *.txt under the dumps tree, windowed by mtime."""
    target = get_dumps_target()
    if not target:
        return []
    inbox = Path(target.inbox).expanduser()
    if not inbox.exists():
        return []
    needle = query.strip().lower()
    start_dt, end_dt = _window_dts(start, end)
    out: list[dict] = []
    for cf in iter_recent_files([inbox], start_dt, end_dt):
        if cf.path.suffix.lower() not in {".md", ".txt"}:
            continue
        try:
            text = cf.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if needle and needle not in text.lower():
            continue
        out.append({"name": cf.path.name, "path": str(cf.path),
                     "text": text[:8000]})
        if len(out) >= limit:
            break
    return out


def _tier3_scan(
    start: Optional[date], end: Optional[date], query: str, limit: int
) -> tuple[list[dict], list[dict]]:
    """Best-effort scan under ${HARQIS_DATA_ROOT} when the corpus is absent."""
    root = _data_root()
    if not root.exists():
        return [], []
    needle = query.strip().lower()
    start_dt, end_dt = _window_dts(start, end)
    texts: list[dict] = []
    media: list[dict] = []
    for p in root.rglob("*"):
        if len(texts) + len(media) >= limit:
            break
        try:
            if not p.is_file():
                continue
            st = p.stat()
            if not (start_dt.timestamp() <= st.st_mtime < end_dt.timestamp()):
                continue
        except OSError:
            continue
        suffix = p.suffix.lower()
        if suffix in (_IMAGE_EXTS | _VIDEO_EXTS):
            media.append({
                "name": p.name, "path": str(p),
                "kind": "video" if suffix in _VIDEO_EXTS else "image",
                "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "bytes": st.st_size, "machine": "",
            })
        elif suffix in {".md", ".txt"}:
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if needle and needle not in text.lower():
                continue
            texts.append({"name": p.name, "path": str(p), "text": text[:8000]})
    return texts, media


# ── Rendering / synthesis ────────────────────────────────────────────────────

def _raw_render(entries: list[dict], summaries: list[dict], media: list[dict]) -> str:
    chunks: list[str] = []
    for s in summaries:
        chunks.append(s.get("text", ""))
    for e in entries:
        chunks.append(f"## {e['date']} — {e.get('header','')}\n{e.get('body','')}")
    if media:
        listing = "\n".join(f"- {m['mtime']}  {m['name']}  ({m.get('kind','')})"
                            for m in media[:200])
        chunks.append(f"### Media in window ({len(media)})\n{listing}")
    return ("\n\n".join(c for c in chunks if c.strip())).strip()


def _synthesize(
    label: str,
    start: Optional[date],
    end: Optional[date],
    entries: list[dict],
    summaries: list[dict],
    media: list[dict],
    model: str,
    cfg_id: str,
    max_tokens: int,
) -> Optional[str]:
    span = (end - start).days if (start and end) else 9999
    if span > _LONG_RANGE_DAYS and summaries:
        body = "\n\n".join(s["text"] for s in summaries)
        body += "\n\n" + "\n\n".join(
            f"## {e['date']} — {e.get('header','')}\n{e.get('body','')}"
            for e in entries[:60]
        )
    else:
        body = _raw_render(entries, summaries, [])
    if media:
        body += "\n\n### Media files in window\n" + "\n".join(
            f"- {m['mtime']}  {m['name']}" for m in media[:150]
        )
    body = body[:_MAX_SYNTH_CHARS]

    user_msg = (
        f"Time window: {label} "
        f"({start or 'beginning'} → {end or 'today'}).\n"
        f"{len(entries)} entries, {len(summaries)} summaries, "
        f"{len(media)} media files.\n\n{body}"
    )
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            logger.warning("memory: Anthropic client not initialized — raw fallback")
            return None
        resp = client.send_message(
            prompt=user_msg,
            system=load_prompt("memory_recall").strip(),
            model=model,
            max_tokens=max_tokens,
        )
        return resp.content[0].text.strip() if resp and resp.content else None
    except Exception as exc:  # any API failure → raw fallback, never raise
        logger.warning("memory: synthesis failed (%s) — raw fallback", exc)
        return None


def _period_dict(start: Optional[date], end: Optional[date], label: str) -> dict:
    return {
        "label": label,
        "start": str(start) if start else None,
        "end": str(end) if end else None,
    }


# ── MCP registration ─────────────────────────────────────────────────────────

def register_memory_tools(mcp: FastMCP):

    @mcp.tool()
    def memory_recall(
        query: str = "",
        period: str = "",
        since: str = "",
        until: str = "",
        detail: str = "summary",
        synthesize: bool = True,
        cfg_id__anthropic: str = "ANTHROPIC",
        model: str = _DEFAULT_HAIKU,
        max_tokens: int = 1500,
    ) -> dict:
        """Reconstruct what happened in a time window from the operator's memory store.

        Tiered: HFL corpus + summaries first; with detail="full" also folds in
        dumps media + dumps-tree text; if the corpus dir is missing/empty,
        falls back to a best-effort scan under ${HARQIS_DATA_ROOT}. Returns
        found=false with empty text (and NO model call) when the window has no
        data. Markdown is returned, never written to disk.

        Args:
            query:  optional case-insensitive substring filter on entries.
            period: "last-week" | "last-month" | "last-3-months" | "ytd" |
                    "last-N-days" | "YYYY" | "YYYY-MM" | "YYYY-Qn" |
                    "YYYY-MM-DD". Overrides since/until when set.
            since:  ISO "YYYY-MM-DD" or relative "-Nd" (used if period empty).
            until:  ISO "YYYY-MM-DD" (defaults to today).
            detail: "summary" (corpus only) or "full" (also dumps media+text).
            synthesize: True → Haiku narrative markdown; False → raw entries.
        """
        logger.info("memory_recall period=%r since=%r until=%r detail=%r q=%r",
                    period, since, until, detail, query)
        start, end, label = _resolve_window(period, since, until)
        corpus_dir = resolve_corpus_dir()
        corpus_missing = not corpus_dir.exists()

        entries: list[dict] = []
        summaries: list[dict] = []
        media: list[dict] = []
        extra_text: list[dict] = []
        tier = 1

        if not corpus_missing:
            entries, summaries = _collect_corpus(corpus_dir, start, end, query)

        if detail == "full":
            tier = 2
            media = _collect_media(start, end, ["image", "video"], 200)
            extra_text = _collect_dumps_text(start, end, query, 30)

        if corpus_missing or (not entries and not summaries):
            t3_text, t3_media = _tier3_scan(start, end, query, 200)
            if t3_text or t3_media:
                tier = 3
                extra_text = extra_text + t3_text
                if not media:
                    media = t3_media

        # Treat dumps/tier-3 text as pseudo-entries for synthesis + raw render.
        for t in extra_text:
            entries.append({"date": "", "header": t["name"],
                            "body": t["text"], "path": t["path"]})

        if not (entries or summaries or media):
            logger.info("memory_recall: no data in window — returning empty")
            return {
                "found": False, "text": "", "hits": [], "media": [],
                "tier": tier, "period": _period_dict(start, end, label),
                "synthesized": False,
            }

        hits = [{"type": "summary", **s} for s in summaries] + \
               [{"type": "entry", **e} for e in entries]

        synthesized = False
        if synthesize:
            text = _synthesize(label, start, end, entries, summaries, media,
                               model, cfg_id__anthropic, max_tokens)
            synthesized = text is not None
            if text is None:
                text = _raw_render(entries, summaries, media)
        else:
            text = _raw_render(entries, summaries, media)

        return {
            "found": True,
            "text": text,
            "hits": hits,
            "media": media,
            "tier": tier,
            "period": _period_dict(start, end, label),
            "synthesized": synthesized,
            "model": model if synthesized else None,
        }

    @mcp.tool()
    def memory_list_media(
        period: str = "",
        since: str = "",
        until: str = "",
        kinds: Optional[list[str]] = None,
        limit: int = 200,
    ) -> dict:
        """List photos/videos captured into the dumps store within a time window.

        Serves "what pictures were stored last week". No LLM, no analysis —
        just an inventory (name/path/machine/kind/mtime/bytes), newest first.
        Returns found=false with an empty list when nothing matched.

        Args:
            period: same vocabulary as memory_recall (overrides since/until).
            since:  ISO "YYYY-MM-DD" or relative "-Nd".
            until:  ISO "YYYY-MM-DD" (defaults to today).
            kinds:  subset of ["image","video"] (default both).
            limit:  max files returned (newest first).
        """
        kinds = kinds or ["image", "video"]
        logger.info("memory_list_media period=%r since=%r until=%r kinds=%r",
                    period, since, until, kinds)
        start, end, label = _resolve_window(period, since, until)
        media = _collect_media(start, end, kinds, limit)
        return {
            "found": bool(media),
            "media": media,
            "count": len(media),
            "period": _period_dict(start, end, label),
        }

    @mcp.tool()
    def git_activity(
        period: str = "",
        since: str = "",
        until: str = "",
        synthesize: bool = True,
        max_repos: int = 30,
        commits_per_repo: int = 50,
        max_commits: int = 200,
        cfg_id__anthropic: str = "ANTHROPIC",
        model: str = _DEFAULT_HAIKU,
    ) -> dict:
        """Live view of the operator's GitHub commits in a time window.

        Same gathering the scheduled ingest_git_activity uses, but read-only
        (no corpus write). Defaults to the last 7 days when no window is
        given. Returns found=false with NO LLM call when there are no
        commits.

        Args:
            period: same vocabulary as memory_recall (overrides since/until).
            since:  ISO "YYYY-MM-DD" or relative "-Nd".
            until:  ISO "YYYY-MM-DD" (defaults to today).
            synthesize: True → Haiku narrative; False → raw per-repo bullets.
        """
        logger.info("git_activity period=%r since=%r until=%r", period, since, until)
        start, end, label = _resolve_window(period, since, until)
        end_d = end or _today()
        start_d = start or (end_d - timedelta(days=6))
        try:
            activity = collect_github_activity(
                since=start_d, until=end_d, max_repos=max_repos,
                commits_per_repo=commits_per_repo, max_commits=max_commits,
            )
        except Exception as exc:  # noqa: BLE001 - surface, don't crash the tool
            logger.warning("git_activity: GitHub unavailable (%s)", exc)
            return {"found": False, "text": "", "error": "github unavailable",
                    "period": _period_dict(start_d, end_d, label)}

        if activity["commit_count"] == 0:
            return {"found": False, "text": "", "repos": [],
                    "commit_count": 0,
                    "period": _period_dict(start_d, end_d, label)}

        d = distill_git_activity(
            activity, synthesize=synthesize, model=model,
            cfg_id=cfg_id__anthropic,
        )
        if synthesize and d.get("synthesized"):
            text = (
                f"**{d['moment']}**\n\n{d['what_happened']}\n\n"
                f"_{d.get('why_it_stayed','')}_"
            ).strip()
        else:
            text = d["what_happened"]  # raw per-repo bullets

        return {
            "found": True,
            "text": text,
            "repos": activity["repos"],
            "commit_count": activity["commit_count"],
            "repo_count": activity["repo_count"],
            "synthesized": d.get("synthesized", False),
            "model": model if d.get("synthesized") else None,
            "period": _period_dict(start_d, end_d, label),
        }
