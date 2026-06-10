"""
workflows/hfl/tasks/ingest_voice.py

Android voice memo transcript -> HFL corpus. Scans a watched inbox directory
for JSON transcript payloads (placed there by the Termux voice_sender helper
or any other Android share flow), distils each into ONE Homework-for-Life entry
(Haiku), and dual-writes it to the Markdown corpus + the harqis-hfl-entries ES
index. Processed files are moved to an inbox/processed/ subfolder so the next
run does not re-ingest them.

File contract (JSON, .json extension):
    {
      "source": "voice_memo",          // always "voice_memo"
      "platform": "android",           // optional: "android", "ios", etc.
      "recorded_at": "2026-06-01T10:30:00",  // required: ISO datetime
      "transcript": "I had a realisation about...",  // required: raw text
      "duration_seconds": 52,          // optional: audio length
      "filename": "memo_20260601.m4a"  // optional: source audio filename
    }

Inbox path resolution (first hit wins):
    1. apps_config.yaml::HFL.voice_inbox.path
    2. Env var VOICE_INBOX_PATH
    3. <corpus_dir>/../voice_inbox/  (resolves to <repo>/logs/voice_inbox/)

Privacy boundaries (hard):
    - Raw transcript is NEVER written to the corpus or ES index. Only the
      distilled HflEntry is persisted.
    - No raw coordinates, no notification bodies, no private names.
    - duration_seconds and filename are used only for context framing; neither
      appears in the HFL entry.

Adhoc task: the beat schedule entry (tasks_config.py) has a disabled Sunday
03:34 slot — the real invocation path is:
    ingest_voice_memos.delay()             from an agent or hotkey
    ingest_voice_memos.apply()             for local testing
    The Termux helper (workflows/mobile/android/voice_sender.py) drops a JSON
    file in the inbox; a Celery worker picks it up on the next .delay() call.

No inbox configured / inbox empty -> no entry, no LLM call (clean no-op).
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic

from workflows.hfl.prompts import load_prompt
from workflows.hfl.tasks.capture import _build_entry, append_entry, resolve_corpus_dir
from workflows.hfl.tasks.ingest_git import _parse_model_json

_log = create_logger("hfl.ingest_voice")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"
_MIN_TRANSCRIPT_CHARS = 20
_MAX_TRANSCRIPT_CHARS = 8000


def resolve_voice_inbox() -> Path:
    """Resolve the voice-memo inbox directory using the documented precedence."""
    try:
        from apps.apps_config import CONFIG_MANAGER
        hfl_cfg = CONFIG_MANAGER.get("HFL")
        if hfl_cfg and isinstance(hfl_cfg, dict):
            inbox_cfg = (hfl_cfg.get("voice_inbox") or {}).get("path")
            if inbox_cfg and "${" not in str(inbox_cfg):
                return Path(inbox_cfg).resolve()
    except Exception:
        pass

    env_path = os.environ.get("VOICE_INBOX_PATH", "").strip()
    if env_path:
        return Path(env_path).resolve()

    corpus_dir = resolve_corpus_dir()
    return (corpus_dir.parent / "voice_inbox").resolve()


def _parse_transcript_file(path: Path) -> Optional[dict]:
    """Parse and validate one inbox JSON file. Returns None on any error."""
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as exc:
        _log.warning("ingest_voice: cannot parse %s (%s) — skipped", path.name, exc)
        return None

    if not isinstance(data, dict):
        _log.warning("ingest_voice: %s is not a JSON object — skipped", path.name)
        return None

    transcript = str(data.get("transcript") or "").strip()
    if len(transcript) < _MIN_TRANSCRIPT_CHARS:
        _log.info("ingest_voice: %s has too-short transcript (%d chars) — skipped",
                  path.name, len(transcript))
        return None

    recorded_at_raw = str(data.get("recorded_at") or "").strip()
    recorded_at: Optional[datetime] = None
    if recorded_at_raw:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                recorded_at = datetime.strptime(recorded_at_raw[:19], fmt)
                break
            except ValueError:
                continue

    return {
        "transcript": transcript[:_MAX_TRANSCRIPT_CHARS],
        "recorded_at": recorded_at or datetime.now(),
        "platform": str(data.get("platform") or "android").strip()[:40],
        "duration_seconds": int(data.get("duration_seconds") or 0),
        "filename": str(data.get("filename") or path.stem)[:120],
        "source_path": path,
    }


def collect_voice_transcripts(inbox_dir: Path) -> list:
    """Scan inbox_dir for *.json transcript files. Returns parsed payloads."""
    if not inbox_dir.is_dir():
        return []
    files = sorted(inbox_dir.glob("*.json"))
    transcripts = []
    for f in files:
        if f.parent.name == "processed":
            continue
        parsed = _parse_transcript_file(f)
        if parsed:
            transcripts.append(parsed)
    return transcripts


def _transcript_context(payload: dict) -> str:
    """Build the user-facing context block for the LLM call."""
    lines = []
    ts = payload["recorded_at"].strftime("%Y-%m-%d %H:%M")
    lines.append("Recorded: " + ts)
    if payload["duration_seconds"] > 0:
        lines.append("Duration: " + str(payload["duration_seconds"]) + "s")
    lines.append("Platform: " + payload["platform"])
    lines.append("")
    lines.append("Transcript:")
    lines.append(payload["transcript"])
    return "\n".join(lines)


def _fallback_distill(payload: dict) -> dict:
    """Raw-fallback distillation (no LLM): first sentence + generic fields."""
    transcript = payload["transcript"]
    first_sentence = transcript.split(".")[0].strip()[:200] or transcript[:200]
    return {
        "skip": False,
        "moment": first_sentence,
        "what_happened": transcript[:400],
        "why_it_stayed": "",
        "possible_use": "voice log",
        "tags": ["voice", payload["platform"]],
        "synthesized": False,
    }


def distill_voice_transcript(
    payload: dict,
    *,
    synthesize: bool = True,
    model: str = _DEFAULT_HAIKU,
    cfg_id: str = "ANTHROPIC",
    max_tokens: int = 700,
) -> dict:
    """Distil a voice transcript payload into HFL entry fields (Haiku, raw fallback)."""
    if not synthesize:
        return _fallback_distill(payload)

    user_msg = _transcript_context(payload)
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            _log.warning("ingest_voice: Anthropic not initialized — raw fallback")
            return _fallback_distill(payload)
        resp = client.send_message(
            prompt=user_msg,
            system=load_prompt("ingest_voice").strip(),
            model=model,
            max_tokens=max_tokens,
        )
        text = resp.content[0].text if resp and resp.content else ""
        parsed = _parse_model_json(text)
        if not parsed:
            return _fallback_distill(payload)
        parsed.setdefault("skip", False)
        for key in ("moment", "what_happened", "why_it_stayed", "possible_use"):
            parsed[key] = str(parsed.get(key, "")).strip()
        parsed["tags"] = [str(t).strip().lstrip("#") for t in (parsed.get("tags") or [])]
        parsed["synthesized"] = True
        return parsed
    except Exception as exc:  # noqa: BLE001 - never break the beat on API error
        _log.warning("ingest_voice: synthesis failed (%s) — raw fallback", exc)
        return _fallback_distill(payload)


def _mark_processed(source_path: Path, inbox_dir: Path) -> None:
    """Move a processed transcript to inbox_dir/processed/ (best-effort)."""
    try:
        processed_dir = inbox_dir / "processed"
        processed_dir.mkdir(exist_ok=True)
        dest = processed_dir / source_path.name
        if dest.exists():
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            dest = processed_dir / (source_path.stem + "_" + ts + source_path.suffix)
        shutil.move(str(source_path), str(dest))
    except Exception as exc:  # noqa: BLE001 - archival failure must not discard the corpus write
        _log.warning("ingest_voice: could not archive %s (%s)", source_path.name, exc)


@SPROUT.task()
@log_result()
def ingest_voice_memos(
    *,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    max_memos: int = 20,
) -> dict:
    """Ingest pending Android voice memo transcripts into the HFL corpus.

    Scans the voice inbox for JSON transcript payloads, distils each into one
    HFL entry (Haiku), dual-writes to corpus + ES, and moves processed files
    to inbox/processed/.

    No inbox configured / inbox empty -> no entry, no LLM call.
    """
    inbox_dir = resolve_voice_inbox()
    if not inbox_dir.is_dir():
        _log.info("ingest_voice: inbox %s does not exist — no-op", inbox_dir)
        return {"skipped": "no inbox", "entries_written": 0, "memos_found": 0}

    transcripts = collect_voice_transcripts(inbox_dir)
    if not transcripts:
        _log.info("ingest_voice: inbox %s is empty — no-op", inbox_dir)
        return {"skipped": "empty inbox", "entries_written": 0, "memos_found": 0}

    transcripts = transcripts[:max_memos]
    _log.info("ingest_voice: processing %d transcript(s) from %s",
              len(transcripts), inbox_dir)

    when = datetime.now()
    corpus_dir = resolve_corpus_dir()
    corpus_dir.mkdir(parents=True, exist_ok=True)
    day_file = corpus_dir / when.strftime("%Y-%m-%d.md")

    entries_written = 0
    skipped = 0
    paths = []

    for payload in transcripts:
        d = distill_voice_transcript(
            payload, synthesize=True, model=model,
            cfg_id=cfg_id__anthropic, max_tokens=700,
        )
        if d.get("skip"):
            _log.info("ingest_voice: %s distilled as skip — not story-worthy",
                      payload["filename"])
            skipped += 1
            _mark_processed(payload["source_path"], inbox_dir)
            continue

        tags = ["voice", payload["platform"]] + [
            str(t) for t in (d.get("tags") or [])
            if str(t).strip() and str(t).strip().lower() not in ("voice", payload["platform"])
        ][:6]

        entry = _build_entry(
            when=payload["recorded_at"],
            moment=d["moment"],
            what_happened=d["what_happened"],
            why_it_stayed=d["why_it_stayed"],
            possible_use=d["possible_use"] or "voice log",
            tags=tags,
            references=[],
        )
        _, doc_id = append_entry(
            day_file, entry, source="voice", synthesized=d.get("synthesized", False),
        )
        _mark_processed(payload["source_path"], inbox_dir)
        entries_written += 1
        paths.append(str(payload["source_path"].name))
        _log.info("ingest_voice: entry written for %s -> %s",
                  payload["filename"], day_file)

    return {
        "entries_written": entries_written,
        "memos_found": len(transcripts),
        "skipped": skipped,
        "model": model,
        "path": str(day_file),
        "processed": paths,
    }
