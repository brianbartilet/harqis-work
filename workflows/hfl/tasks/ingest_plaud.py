"""
workflows/hfl/tasks/ingest_plaud.py

Daily Plaud voice-recordings → HFL corpus. Pulls the day's recordings from the
Plaud adapter (apps/plaud — cloud API primary, local export-folder fallback),
and for EACH recording distils its transcript into ONE Homework-for-Life entry,
dual-writing it (Markdown corpus + the harqis-hfl-entries ES index, source
"plaud"). Unlike the other ingest sources this writes one entry *per recording*,
not a single daily digest — each conversation/meeting/note is its own moment.

Transcript precedence (per the approved spec — subscription-fee aware):
  1. Plaud's own transcript (free if you keep a Plaud subscription).
  2. If absent, download the audio and transcribe with OpenAI Whisper
     (OPENAI_API_KEY). Bounded by `max_transcribe` so Whisper cost stays capped.
  3. If neither yields text, the recording is skipped (no LLM, no entry).

Two extras beyond the standard ingest pattern (clearly seamed below):
  - Whisper transcription fallback — `_ensure_transcript`.
  - Archive: raw recordings + a consolidated YYYY-MM-DD-summary.md are pushed to
    harqis-ones-mac-mini over SSH (passwordless key) — `_archive_day`.

No acquisition backend ready (no PLAUD_EMAIL+PLAUD_PASSWORD, no PLAUD_TOKEN,
and no PLAUD_EXPORT_DIR) → no entry, no network call (clean no-op, mirrors
ingest_chatgpt on a no-token day). No recordings in the window → no entry, no
LLM call.

Never breaks the beat: every external failure (Plaud, Whisper, Anthropic, the
Mac-mini archive) is caught and turned into a logged skip / surfaced in the
result dict — the corpus + ES writes always happen first, so a failed archive
never costs a captured entry.

Config (env, resolved by deploy.py / .env/apps.env):
  PLAUD_EMAIL          web.plaud.ai login — adapter mints/refreshes its own
  PLAUD_PASSWORD       ~30-day token (preferred; see apps/plaud/README.md)
  PLAUD_TOKEN          manual cloud bearer (fallback; expires periodically)
  PLAUD_EXPORT_DIR     local export folder (fallback acquisition path)
  OPENAI_API_KEY       Whisper transcription fallback
  PLAUD_ARCHIVE_HOST   SSH host for the archive (default: harqis-ones-mac-mini)
  PLAUD_ARCHIVE_PATH   remote base dir for the archive (unset → archive skipped)

The collectors (collect_plaud_recordings / distill_plaud_recording) are plain
functions so the MCP tool (plaud_activity) can reuse them for a live, no-write
view.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
from apps.plaud.config import CONFIG as PLAUD_CONFIG
from apps.plaud.references.adapter import build_adapter
from apps.plaud.references.dto.recording import DtoPlaudRecording

from workflows.hfl.dto import HflEntry
from workflows.hfl.es_store import index_hfl_entry
from workflows.hfl.prompts import load_prompt
from workflows.hfl.tasks.capture import resolve_corpus_dir
from workflows.hfl.tasks.ingest_git import _parse_model_json

_log = create_logger("hfl.ingest_plaud")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"
_DEFAULT_ARCHIVE_HOST = "harqis-ones-mac-mini"

# OpenAI Whisper rejects uploads over 25 MB. Stay just under, and split anything
# larger into compressed segments (16 kHz mono MP3 ≈ 0.5 MB/min) so every chunk
# clears the cap — a 10-min segment is ~5 MB. Transcripts are stitched in order.
_WHISPER_MAX_BYTES = 24 * 1024 * 1024
_WHISPER_CHUNK_SECONDS = 600


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "recording"


def _coerce_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


# ── transcription fallback (seam) ─────────────────────────────────────────────

def _whisper_one(client, audio_path: str, model: str) -> Optional[str]:
    """Transcribe a single under-cap file. Raises on API error (caller guards)."""
    with open(audio_path, "rb") as fh:
        resp = client.audio.transcriptions.create(model=model, file=fh)
    return (getattr(resp, "text", "") or "").strip() or None


def _segment_audio_for_whisper(audio_path: str, out_dir: str) -> list[str]:
    """Transcode to 16 kHz mono MP3 and split into <=``_WHISPER_CHUNK_SECONDS``
    segments (~5 MB each at 64 kbps) so every chunk clears Whisper's 25 MB cap.

    Returns the chunk paths in playback order, or [] if ffmpeg is missing/fails
    (caller then cleanly skips the recording)."""
    pattern = os.path.join(out_dir, "chunk_%04d.mp3")
    try:
        subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
             "-i", audio_path, "-ac", "1", "-ar", "16000", "-b:a", "64k",
             "-f", "segment", "-segment_time", str(_WHISPER_CHUNK_SECONDS),
             pattern],
            check=True, capture_output=True, timeout=1800,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        err = getattr(exc, "stderr", b"") or b""
        _log.warning("ingest_plaud: ffmpeg segmenting failed for %s (%s) %s",
                     audio_path, exc, err.decode("utf-8", "replace")[:200] if err else "")
        return []
    return sorted(str(p) for p in Path(out_dir).glob("chunk_*.mp3"))


def _transcribe_with_whisper(audio_path: str, *, model: str = "whisper-1") -> Optional[str]:
    """Transcribe an audio file with OpenAI Whisper. Files over the 25 MB API cap
    are transcoded + split into segments (ffmpeg) and stitched. Best-effort:
    returns None on any failure (missing key, missing package, missing ffmpeg,
    API error) so the caller cleanly skips rather than breaking the beat."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        _log.info("ingest_plaud: OPENAI_API_KEY not set — cannot Whisper-transcribe")
        return None
    if not audio_path or not os.path.exists(audio_path):
        return None
    try:
        from openai import OpenAI  # native client (openai>=1.50, see requirements.txt)

        client = OpenAI(api_key=key)
        if os.path.getsize(audio_path) <= _WHISPER_MAX_BYTES:
            return _whisper_one(client, audio_path, model)
        # Over the cap: segment into compressed chunks, transcribe each in order.
        with tempfile.TemporaryDirectory(prefix="plaud-whisper-") as tmp:
            chunks = _segment_audio_for_whisper(audio_path, tmp)
            if not chunks:
                return None
            _log.info("ingest_plaud: %s over 25MB — transcribing %d chunk(s)",
                      os.path.basename(audio_path), len(chunks))
            parts: list[str] = []
            for i, chunk in enumerate(chunks, 1):
                text = _whisper_one(client, chunk, model)
                if text:
                    parts.append(text)
                _log.info("ingest_plaud:   chunk %d/%d -> %d chars",
                          i, len(chunks), len(text or ""))
            return "\n".join(parts).strip() or None
    except Exception as exc:  # noqa: BLE001 - transcription is best-effort
        _log.warning("ingest_plaud: Whisper transcription failed for %s (%s)",
                     audio_path, exc)
        return None


def _ensure_transcript(
    rec: DtoPlaudRecording,
    *,
    adapter,
    audio_dir: str,
    allow_whisper: bool,
    whisper_model: str = "whisper-1",
) -> Optional[str]:
    """Prefer Plaud's own transcript; fall back to Whisper on the raw audio.

    Downloads the audio into ``audio_dir`` (also the archive staging dir) when
    Whisper is needed. Returns the transcript text, or None if neither path
    produced one.
    """
    if rec.has_transcript:
        return rec.transcript.strip()
    if not allow_whisper:
        return None
    local_audio = adapter.ensure_audio_local(rec, audio_dir)
    if not local_audio:
        _log.info("ingest_plaud: no audio available to transcribe for %s", rec.id)
        return None
    return _transcribe_with_whisper(local_audio, model=whisper_model)


# ── collect + distill (MCP-reusable plain functions) ──────────────────────────

def collect_plaud_recordings(
    *,
    since: date,
    until: date,
    adapter,
    max_recordings: int = 50,
) -> dict[str, Any]:
    """List Plaud recordings in [since, until] via the adapter (cloud → folder).

    Returns:
        {"recordings": [DtoPlaudRecording, ...], "count": int,
         "backend": <active backend name or None>}
    """
    since_iso = since.strftime("%Y-%m-%dT00:00:00")
    until_iso = until.strftime("%Y-%m-%dT23:59:59")
    recs = adapter.list_recordings(since=since_iso, until=until_iso) or []
    recs = recs[:max_recordings]
    return {
        "recordings": recs,
        "count": len(recs),
        "backend": adapter.status.get("active"),
    }


def distill_plaud_recording(
    rec: DtoPlaudRecording,
    transcript: str,
    *,
    synthesize: bool = True,
    model: str = _DEFAULT_HAIKU,
    cfg_id: str = "ANTHROPIC",
    max_tokens: int = 900,
) -> dict[str, Any]:
    """Turn one recording's transcript into HFL entry fields (Haiku, raw fallback)."""

    def _fallback() -> dict:
        preview = (transcript or "").strip().replace("\n", " ")[:280]
        title = rec.title or "Voice recording"
        return {
            "skip": False,
            "moment": f"Voice recording: {title}"[:120],
            "what_happened": rec.summary.strip() if rec.summary else preview,
            "why_it_stayed": "",
            "possible_use": "voice-note",
            "tags": ["voice", "plaud"],
            "synthesized": False,
        }

    if not synthesize or not (transcript or "").strip():
        return _fallback()

    header = f"Title: {rec.title or '(untitled)'}\nWhen: {rec.started_at or '(unknown)'}"
    user_msg = f"{header}\n\nTranscript:\n{transcript.strip()[:50000]}"
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            _log.warning("ingest_plaud: Anthropic not initialized — raw fallback")
            return _fallback()
        resp = client.send_message(
            prompt=user_msg,
            system=load_prompt("ingest_plaud").strip(),
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
        parsed["tags"] = [str(t).strip().lstrip("#") for t in (parsed.get("tags") or [])]
        parsed["synthesized"] = True
        return parsed
    except Exception as exc:  # noqa: BLE001 - never break the beat on API error
        _log.warning("ingest_plaud: synthesis failed (%s) — raw fallback", exc)
        return _fallback()


# ── archive to Mac mini (seam) ────────────────────────────────────────────────

def _build_day_summary_md(day: str, items: list[dict]) -> str:
    """Consolidated Markdown summary of all of a day's recordings."""
    lines = [f"# Plaud recordings — {day}", "", f"_{len(items)} recording(s)._", ""]
    for it in items:
        lines.append(f"## {it['title']}")
        if it.get("started_at"):
            lines.append(f"*{it['started_at']}*")
        lines.append("")
        lines.append(f"**Moment:** {it.get('moment', '')}")
        lines.append("")
        if it.get("summary"):
            lines.append(it["summary"])
            lines.append("")
        if it.get("transcript"):
            lines.append("<details><summary>Transcript</summary>")
            lines.append("")
            lines.append(it["transcript"])
            lines.append("")
            lines.append("</details>")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _is_local_archive_host(host: str) -> bool:
    """Return True when the configured archive host is this machine.

    The HARQIS Mac mini often has PLAUD_ARCHIVE_PATH mounted locally. In that
    case routing the archive through SSH-to-self makes the nightly job depend on
    local public-key auth even though a direct filesystem copy is enough.
    """
    normalized = (host or "").strip().split("@")[-1].lower().rstrip(".")
    if normalized in {"", "localhost", "127.0.0.1", "::1"}:
        return True
    candidates = {
        socket.gethostname(),
        socket.getfqdn(),
        os.environ.get("HOSTNAME", ""),
    }
    try:
        candidates.add(subprocess.check_output(["scutil", "--get", "LocalHostName"], text=True).strip())
    except Exception:  # noqa: BLE001 - macOS helper may not exist off-host
        pass
    return normalized in {c.lower().rstrip(".") for c in candidates if c}


def _archive_day(staging_dir: Path, day: str) -> dict[str, Any]:
    """Archive the day's staging folder (audio + summary.md).

    If the configured target is this host and PLAUD_ARCHIVE_PATH is an absolute
    local path, copy directly. Otherwise scp to the configured archive host.
    Best-effort: returns {"archived": bool, "error"?: str}. Never raises — a
    failed archive must not cost an already-captured HFL entry.
    """
    remote_base = os.environ.get("PLAUD_ARCHIVE_PATH", "").strip()
    if not remote_base:
        return {"archived": False, "skipped": "PLAUD_ARCHIVE_PATH not set"}
    host = os.environ.get("PLAUD_ARCHIVE_HOST", "").strip() or _DEFAULT_ARCHIVE_HOST
    if Path(remote_base).is_absolute() and _is_local_archive_host(host):
        target_dir = Path(remote_base) / staging_dir.name
        try:
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(staging_dir, target_dir, dirs_exist_ok=True)
            _log.info("ingest_plaud: archived %s → %s", day, target_dir)
            return {"archived": True, "host": host, "remote_base": remote_base, "mode": "local-copy"}
        except Exception as exc:  # noqa: BLE001 - archive must never break the beat
            _log.error("ingest_plaud: local archive to %s failed (%s)", target_dir, exc)
            return {"archived": False, "error": str(exc)[:200], "mode": "local-copy"}

    target = f"{host}:{remote_base.rstrip('/')}/"
    try:
        # -r recursive, -B batch (never prompt for a password — key-only),
        # -o BatchMode=yes so a missing key fails fast instead of hanging.
        subprocess.run(
            ["scp", "-r", "-B", "-o", "BatchMode=yes", str(staging_dir), target],
            check=True,
            capture_output=True,
            timeout=600,
        )
        _log.info("ingest_plaud: archived %s → %s", day, target)
        return {"archived": True, "host": host, "remote_base": remote_base, "mode": "scp"}
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or b"").decode("utf-8", "replace").strip()[:200]
        _log.error("ingest_plaud: archive to %s failed: %s", target, err)
        return {"archived": False, "error": err or "scp failed", "mode": "scp"}
    except Exception as exc:  # noqa: BLE001 - archive must never break the beat
        _log.error("ingest_plaud: archive to %s failed (%s)", target, exc)
        return {"archived": False, "error": str(exc)[:200], "mode": "scp"}


# ── task ──────────────────────────────────────────────────────────────────────

@SPROUT.task()
@log_result()
def ingest_plaud_activity(
    *,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    window_days: int = 1,
    max_recordings: int = 50,
    max_transcribe: int = 20,
    whisper_model: str = "whisper-1",
    allow_whisper: bool = True,
    archive: bool = True,
) -> dict[str, Any]:
    """Ingest the day's Plaud recordings — one HFL entry per recording.

    No acquisition backend ready (no PLAUD_TOKEN, no PLAUD_EXPORT_DIR) → no
    entry, no network call. No recordings in the window → no entry, no LLM call.
    """
    adapter = build_adapter(PLAUD_CONFIG)
    status = adapter.status
    if not status.get("active"):
        _log.info("ingest_plaud: no acquisition backend ready (no token / folder) — no-op")
        return {"skipped": "no backend", "entries_written": 0, "recordings": 0}

    until = datetime.now().date()
    since = until - timedelta(days=window_days)

    try:
        collected = collect_plaud_recordings(
            since=since, until=until, adapter=adapter, max_recordings=max_recordings,
        )
    except Exception as exc:  # noqa: BLE001 - acquisition down/changed must not break beat
        _log.error("ingest_plaud: acquisition failed (%s)", exc)
        return {"skipped": "acquisition unavailable", "entries_written": 0,
                "error": str(exc)[:200]}

    recordings: list[DtoPlaudRecording] = collected["recordings"]
    if not recordings:
        _log.info("ingest_plaud: no recordings in last %d day(s)", window_days)
        return {"skipped": "no recordings", "entries_written": 0, "recordings": 0}

    corpus_dir = resolve_corpus_dir()
    corpus_dir.mkdir(parents=True, exist_ok=True)
    day_str = until.strftime("%Y-%m-%d")

    # Staging dir for audio + the consolidated summary (also what gets archived).
    staging_root = Path(tempfile.mkdtemp(prefix="plaud-"))
    staging_dir = staging_root / day_str
    staging_dir.mkdir(parents=True, exist_ok=True)

    entries_written = 0
    transcribed = 0
    summary_items: list[dict] = []

    for rec in recordings:
        # 1. Transcript: Plaud's own, else Whisper (bounded by max_transcribe).
        may_whisper = allow_whisper and transcribed < max_transcribe
        transcript = _ensure_transcript(
            rec, adapter=adapter, audio_dir=str(staging_dir),
            allow_whisper=may_whisper, whisper_model=whisper_model,
        )
        if transcript and not rec.has_transcript:
            transcribed += 1
        if not transcript and not rec.summary:
            _log.info("ingest_plaud: %s has no transcript/summary — skipped", rec.id)
            continue

        # 2. Distil one recording → HFL fields.
        d = distill_plaud_recording(
            rec, transcript or "", synthesize=bool(transcript),
            model=model, cfg_id=cfg_id__anthropic,
        )
        if d.get("skip"):
            _log.info("ingest_plaud: %s distilled as skip (not story-worthy)", rec.id)
            continue

        # 3. Build the entry + dual-write (corpus + ES) with a per-recording
        #    deterministic doc id so re-runs upsert instead of duplicating.
        when = _coerce_date(rec.started_at)
        when_dt = datetime.combine(when, datetime.min.time()) if when else datetime.now()
        tags = ["voice", "plaud"] + [
            str(t) for t in (d.get("tags") or []) if str(t).strip()
        ][:6]
        entry = HflEntry(
            when=when_dt,
            moment=d["moment"],
            what_happened=d["what_happened"],
            why_it_stayed=d["why_it_stayed"],
            possible_use=d["possible_use"] or "voice-note",
            tags=tags,
            references=[f"plaud:{rec.id}"],
        )
        day_file = corpus_dir / f"{when_dt.strftime('%Y-%m-%d')}.md"
        with day_file.open("a", encoding="utf-8") as fh:
            fh.write(entry.to_markdown())
        doc_id = f"{when_dt.strftime('%Y%m%d')}-plaud-{_slug(rec.id)}"
        index_hfl_entry(entry, source="plaud",
                        synthesized=d.get("synthesized", False), doc_id=doc_id)
        entries_written += 1

        summary_items.append({
            "title": rec.title or rec.id,
            "started_at": rec.started_at,
            "moment": d["moment"],
            "summary": rec.summary or "",
            "transcript": transcript or "",
        })

    # 4. Archive: write the consolidated summary into staging, then push the
    #    whole day folder (audio already downloaded there + summary) to the host.
    archive_result: dict[str, Any] = {"archived": False, "skipped": "archive disabled"}
    if archive and summary_items:
        summary_path = staging_dir / f"{day_str}-summary.md"
        summary_path.write_text(_build_day_summary_md(day_str, summary_items),
                                encoding="utf-8")
        archive_result = _archive_day(staging_dir, day_str)

    # Staging held only the audio + summary for the archive push; the corpus +
    # ES (and the archived copy) are the durable artifacts. Drop it so temp
    # audio doesn't accumulate across nightly runs.
    shutil.rmtree(staging_root, ignore_errors=True)

    _log.info("ingest_plaud: %d entr(y/ies) from %d recording(s) (%d Whisper) -> %s",
              entries_written, len(recordings), transcribed, corpus_dir)
    return {
        "entries_written": entries_written,
        "recordings": len(recordings),
        "transcribed_whisper": transcribed,
        "backend": collected.get("backend"),
        "archive": archive_result,
        "model": model,
        "path": str(corpus_dir / f"{day_str}.md"),
    }
