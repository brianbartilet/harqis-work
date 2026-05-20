"""
workflows/hfl/tasks/ingest_browsing.py

Daily web-browsing → HFL corpus. Reads the day's Chrome and Edge history
straight off the local `History` SQLite databases, distils it into ONE
Homework-for-Life entry (Haiku), and dual-writes it (Markdown corpus +
the harqis-hfl-entries ES index) so the day's browsing flows into
summarize_hfl_week + the memory_recall MCP automatically.

Fanout (hfl_broadcast)
----------------------
This task is broadcast to every Celery worker subscribed to the
``hfl_broadcast`` queue (see workflows/config.py + machines.toml). Each
worker independently reads ITS OWN local browser history and produces one
entry per day, so a multi-machine setup captures each device's browsing
without any cross-machine coordination. Workers with no `History` DB (e.g.
headless servers) no-op cleanly — no LLM, no entry. The ES doc id is
deterministic on (date, source="browsing", moment-hash), so two machines'
distinct browsing produces two distinct docs; the corpus daily file gets
one ``## …`` block appended per contributing machine.

Why this exists (and the caveats — read these):
  - There is no "browsing history API". Chromium browsers keep history in
    a local SQLite DB; this task reads it directly. No app integration is
    involved (apps/browser is a remote URL fetcher, not a history reader),
    so the collector is self-contained — exactly like ingest_chatgpt's
    private-backend client.
  - The browser holds an exclusive lock on `History` while running, so we
    copy the DB to a temp file and open the copy read-only. Visits still
    buffered in the `-wal` sidecar (not yet checkpointed into the main DB)
    are not visible until the browser flushes them — a small recency gap,
    acceptable for a once-a-day digest. We copy the `-wal`/`-shm` sidecars
    too when present so most recent visits are picked up.
  - This is the operator's own machine and own browsing for a personal
    log. No domain filtering is applied by default (the operator opted
    into the full picture); an optional `exclude_domains` list is the
    escape hatch. Volume is hard-capped so the prompt stays bounded and
    the beat never breaks.
  - Only the *Default* profile of each browser is read. Override the DB
    locations with HFL_BROWSING_CHROME_HISTORY / HFL_BROWSING_EDGE_HISTORY
    (absolute paths) for non-default profiles or a non-Windows layout.

No history DBs found → no entry, no LLM call (clean no-op, mirrors
ingest_git_activity on a no-commit day). No visits in the window →
no entry, no LLM call.

Config (env, optional — resolved by deploy.py / .env/apps.env):
  HFL_BROWSING_CHROME_HISTORY  optional — absolute path to Chrome's
                               `History` DB (default: %LOCALAPPDATA%\\
                               Google\\Chrome\\User Data\\Default\\History).
  HFL_BROWSING_EDGE_HISTORY    optional — absolute path to Edge's
                               `History` DB (default: %LOCALAPPDATA%\\
                               Microsoft\\Edge\\User Data\\Default\\History).

The collectors (collect_browsing_activity / distill_browsing_activity)
are plain functions so an MCP tool can reuse them for a live, no-write
view.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from datetime import date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlsplit

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic

from workflows.hfl.prompts import load_prompt
from workflows.hfl.tasks.capture import (
    _build_entry,
    append_entry,
    resolve_corpus_dir,
)
from workflows.hfl.tasks.ingest_git import _parse_model_json

_log = create_logger("hfl.ingest_browsing")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"

# Seconds between the Chrome/WebKit epoch (1601-01-01 UTC) and the Unix
# epoch (1970-01-01 UTC). Chromium stores visit_time as microseconds since
# the WebKit epoch.
_CHROME_EPOCH_OFFSET = 11_644_473_600

# References (notable URLs) stored on the entry, capped — provenance, not
# a full dump.
_MAX_REFERENCES = 10


def _default_history_paths() -> dict[str, str]:
    """Per-browser Default-profile `History` DB paths, env-overridable.

    Returns only the browsers whose DB path resolves to an existing file.
    """
    local = os.environ.get("LOCALAPPDATA", "").strip()
    candidates = {
        "chrome": os.environ.get("HFL_BROWSING_CHROME_HISTORY", "").strip()
        or (
            os.path.join(
                local, "Google", "Chrome", "User Data", "Default", "History"
            )
            if local
            else ""
        ),
        "edge": os.environ.get("HFL_BROWSING_EDGE_HISTORY", "").strip()
        or (
            os.path.join(
                local, "Microsoft", "Edge", "User Data", "Default", "History"
            )
            if local
            else ""
        ),
    }
    return {b: p for b, p in candidates.items() if p and os.path.isfile(p)}


def _to_chrome_time(dt: datetime) -> int:
    """A naive local datetime → Chromium visit_time (µs since 1601)."""
    return int((dt.timestamp() + _CHROME_EPOCH_OFFSET) * 1_000_000)


def _from_chrome_time(value: int) -> Optional[datetime]:
    """Chromium visit_time (µs since 1601) → naive local datetime."""
    try:
        return datetime.fromtimestamp(value / 1_000_000 - _CHROME_EPOCH_OFFSET)
    except (ValueError, OSError, OverflowError):
        return None


def _domain(url: str) -> str:
    try:
        host = urlsplit(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except ValueError:
        return ""


def _read_browser_history(
    db_path: str,
    *,
    lo: int,
    hi: int,
    max_rows: int,
) -> list[dict]:
    """Read [lo, hi] visits from one Chromium `History` DB.

    Copies the DB (+ -wal/-shm sidecars) to a temp dir first because the
    running browser holds an exclusive lock on the original. Read-only,
    best-effort: any sqlite/IO error raises and the caller turns it into a
    skip for that browser (never a broken beat).
    """
    tmpdir = tempfile.mkdtemp(prefix="hfl-browsing-")
    try:
        tmp_db = os.path.join(tmpdir, "History")
        shutil.copy2(db_path, tmp_db)
        for ext in ("-wal", "-shm"):
            side = db_path + ext
            if os.path.isfile(side):
                try:
                    shutil.copy2(side, tmp_db + ext)
                except OSError:
                    pass  # sidecar optional — main DB is enough
        conn = sqlite3.connect(f"file:{tmp_db}?mode=ro", uri=True)
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT u.url AS url, u.title AS title,
                       u.visit_count AS visit_count, v.visit_time AS visit_time
                  FROM visits v
                  JOIN urls u ON u.id = v.url
                 WHERE v.visit_time BETWEEN ? AND ?
                 ORDER BY v.visit_time ASC
                 LIMIT ?
                """,
                (lo, hi, max_rows),
            ).fetchall()
        finally:
            conn.close()
        out: list[dict] = []
        for r in rows:
            when = _from_chrome_time(r["visit_time"])
            url = (r["url"] or "").strip()
            if not when or not url:
                continue
            out.append({
                "when": when,
                "url": url,
                "title": (r["title"] or "").strip(),
                "visit_count": int(r["visit_count"] or 0),
            })
        return out
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def collect_browsing_activity(
    *,
    since: date,
    until: date,
    browsers: tuple[str, ...] = ("chrome", "edge"),
    max_visits: int = 600,
    exclude_domains: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Read Chrome/Edge history for [since, until], aggregate by domain.

    `max_visits` is split across the configured browsers so one chatty
    browser can't crowd the other out, then the merged set is trimmed to
    the cap. `exclude_domains` is an exact host match (after stripping a
    leading "www.") — empty by default (no filtering).

    Returns:
        {"visits": [{"when","url","domain","title","visit_count"}],
         "domains": [{"domain","visits","top_title"}],   # busiest first
         "visit_count", "domain_count", "browsers_read", "history_found"}
    """
    paths = _default_history_paths()
    requested = {b for b in browsers if b in paths}
    if not requested:
        return {
            "visits": [], "domains": [], "visit_count": 0,
            "domain_count": 0, "browsers_read": [],
            "history_found": bool(paths),
        }

    lo = _to_chrome_time(datetime.combine(since, datetime.min.time()))
    hi = _to_chrome_time(datetime.combine(until, datetime.max.time()))
    per_browser_cap = max(1, max_visits // max(1, len(requested)))
    deny = {d.strip().lower().lstrip(".") for d in exclude_domains if d.strip()}

    merged: list[dict] = []
    browsers_read: list[str] = []
    for browser in sorted(requested):
        try:
            rows = _read_browser_history(
                paths[browser], lo=lo, hi=hi, max_rows=per_browser_cap,
            )
        except Exception as exc:  # noqa: BLE001 - one bad DB must not abort
            _log.info(
                "ingest_browsing: could not read %s history (%s)", browser, exc
            )
            continue
        browsers_read.append(browser)
        for r in rows:
            dom = _domain(r["url"])
            if not dom or dom in deny:
                continue
            r["domain"] = dom
            r["browser"] = browser
            merged.append(r)

    merged.sort(key=lambda r: r["when"])
    if len(merged) > max_visits:
        merged = merged[:max_visits]

    agg: dict[str, dict] = {}
    for r in merged:
        d = agg.setdefault(
            r["domain"], {"domain": r["domain"], "visits": 0, "top_title": ""}
        )
        d["visits"] += 1
        if not d["top_title"] and r["title"]:
            d["top_title"] = r["title"][:160]
    domains = sorted(agg.values(), key=lambda d: d["visits"], reverse=True)

    return {
        "visits": [
            {
                "when": r["when"].strftime("%Y-%m-%d %H:%M"),
                "url": r["url"],
                "domain": r["domain"],
                "title": r["title"][:200],
                "visit_count": r["visit_count"],
            }
            for r in merged
        ],
        "domains": domains,
        "visit_count": len(merged),
        "domain_count": len(domains),
        "browsers_read": browsers_read,
        "history_found": True,
    }


def _activity_body(activity: dict) -> str:
    """Compact, model-friendly view: busiest domains + notable page titles."""
    lines: list[str] = ["## Busiest domains"]
    for d in activity["domains"][:25]:
        title = d["top_title"] or "(no title)"
        lines.append(f"- {d['domain']}: {d['visits']} visit(s) — e.g. {title}")
    # A flat, de-duplicated sample of distinct page titles for texture.
    seen: set[str] = set()
    notable: list[str] = []
    for v in activity["visits"]:
        t = v["title"].strip()
        key = (v["domain"], t.lower())
        if not t or key in seen:
            continue
        seen.add(key)
        notable.append(f"- [{v['domain']}] {t}")
        if len(notable) >= 60:
            break
    if notable:
        lines.append("\n## Distinct pages")
        lines.extend(notable)
    return "\n".join(lines)


def _top_references(activity: dict) -> list[str]:
    """Up to _MAX_REFERENCES representative URLs (most-visited distinct)."""
    best: dict[str, dict] = {}
    for v in activity["visits"]:
        cur = best.get(v["url"])
        if cur is None or v["visit_count"] > cur["visit_count"]:
            best[v["url"]] = v
    ranked = sorted(
        best.values(), key=lambda v: v["visit_count"], reverse=True
    )
    return [v["url"] for v in ranked[:_MAX_REFERENCES]]


def distill_browsing_activity(
    activity: dict,
    *,
    synthesize: bool = True,
    model: str = _DEFAULT_HAIKU,
    cfg_id: str = "ANTHROPIC",
    max_tokens: int = 900,
) -> dict[str, Any]:
    """Turn collected browsing into HFL entry fields (Haiku, raw fallback)."""
    visit_count = activity["visit_count"]
    domain_count = activity["domain_count"]

    def _fallback() -> dict:
        bullets = [
            f"- {d['domain']}: {d['visits']} visit(s)"
            for d in activity["domains"][:12]
        ]
        return {
            "skip": False,
            "moment": (
                f"{visit_count} page visit(s) across {domain_count} site(s)"
            ),
            "what_happened": "\n".join(bullets),
            "why_it_stayed": "",
            "possible_use": "research-log",
            "tags": ["browsing", "web"],
            "synthesized": False,
        }

    if not synthesize:
        return _fallback()

    user_msg = (
        f"The day's browser history: {visit_count} visits across "
        f"{domain_count} domains (browsers: "
        f"{', '.join(activity['browsers_read']) or 'none'}).\n\n"
        f"{_activity_body(activity)}"
    )
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            _log.warning("ingest_browsing: Anthropic not initialized — raw fallback")
            return _fallback()
        resp = client.send_message(
            prompt=user_msg,
            system=load_prompt("ingest_browsing").strip(),
            model=model,
            max_tokens=max_tokens,
        )
        text = resp.content[0].text if resp and resp.content else ""
        parsed = _parse_model_json(text)
        if not parsed:
            return _fallback()
        parsed.setdefault("skip", False)
        for key in ("moment", "what_happened", "why_it_stayed", "possible_use"):
            parsed[key] = str(parsed.get(key, "")).strip()
        parsed["tags"] = [
            str(t).strip().lstrip("#") for t in (parsed.get("tags") or [])
        ]
        parsed["synthesized"] = True
        return parsed
    except Exception as exc:  # noqa: BLE001 - never break the beat on API error
        _log.warning("ingest_browsing: synthesis failed (%s) — raw fallback", exc)
        return _fallback()


@SPROUT.task()
@log_result()
def ingest_browsing_activity(
    *,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    window_days: int = 1,
    browsers: tuple[str, ...] = ("chrome", "edge"),
    max_visits: int = 600,
    exclude_domains: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Append one HFL corpus entry summarizing the day's web browsing.

    No Chrome/Edge history DB found → no entry, no LLM call.
    No visits in the window → no entry, no LLM call.
    """
    until = datetime.now().date()
    since = until - timedelta(days=window_days)

    try:
        activity = collect_browsing_activity(
            since=since, until=until, browsers=browsers,
            max_visits=max_visits, exclude_domains=exclude_domains,
        )
    except Exception as exc:  # noqa: BLE001 - DB issues must not break beat
        _log.error("ingest_browsing: history unavailable (%s)", exc)
        return {"skipped": "history unavailable", "entries_written": 0,
                "error": str(exc)[:200]}

    if not activity["history_found"]:
        _log.info("ingest_browsing: no Chrome/Edge history DB found — no-op")
        return {"skipped": "no history db", "entries_written": 0, "visits": 0}

    if activity["visit_count"] == 0:
        _log.info("ingest_browsing: no visits in last %d day(s)", window_days)
        return {"skipped": "no visits", "entries_written": 0, "visits": 0}

    d = distill_browsing_activity(
        activity, synthesize=True, model=model,
        cfg_id=cfg_id__anthropic, max_tokens=900,
    )
    if d.get("skip"):
        _log.info("ingest_browsing: distilled as skip — %d visits not "
                  "story-worthy", activity["visit_count"])
        return {"skipped": "distilled-skip", "entries_written": 0,
                "visit_count": activity["visit_count"]}

    tags = ["browsing", "web"] + [
        str(t) for t in (d.get("tags") or []) if str(t).strip()
    ][:6]

    when = datetime.now()
    corpus_dir = resolve_corpus_dir()
    corpus_dir.mkdir(parents=True, exist_ok=True)
    day_file = corpus_dir / f"{when.strftime('%Y-%m-%d')}.md"

    entry = _build_entry(
        when=when,
        moment=d["moment"],
        what_happened=d["what_happened"],
        why_it_stayed=d["why_it_stayed"],
        possible_use=d["possible_use"] or "research-log",
        tags=tags,
        # Provenance: the day's most-visited pages (manifesto §2 — an
        # hfl_signal entry references its source artifacts).
        references=_top_references(activity),
    )
    _bytes, doc_id = append_entry(
        day_file, entry,
        source="browsing", synthesized=d.get("synthesized", False),
    )

    _log.info("ingest_browsing: entry written (%d visits, %d domains) → %s",
              activity["visit_count"], activity["domain_count"], day_file)
    return {
        "entries_written": 1,
        "indexed": doc_id is not None,
        "visits": activity["visit_count"],
        "domains": activity["domain_count"],
        "browsers": activity["browsers_read"],
        "synthesized": d.get("synthesized", False),
        "model": model if d.get("synthesized") else None,
        "path": str(day_file),
    }
