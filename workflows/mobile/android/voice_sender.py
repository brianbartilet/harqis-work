"""
workflows/mobile/android/voice_sender.py

Termux/Android helper -- converts a voice memo transcript into the JSON
payload format consumed by workflows/hfl/tasks/ingest_voice.py and saves it
to the harqis-work voice inbox.

Usage (on Android via Termux):
  # From share intent (text passed as argument):
  python voice_sender.py --text "I realised today that..."

  # From clipboard:
  python voice_sender.py --clipboard

  # From stdin (pipe a transcript):
  echo "Voice memo text" | python voice_sender.py

  # Optionally specify metadata:
  python voice_sender.py --text "..." --duration 52 --filename "memo.m4a"

Output:
  Writes a JSON file to VOICE_INBOX_PATH (env) or ~/storage/shared/voice_inbox/
  File format: voice_YYYYMMDD_HHMMSS.json

  Optionally POSTs to HARQIS_VOICE_SUBMIT_URL if set (e.g. a Celery webhook or
  a simple HTTP receiver on harqis-server). Raw transcript is never logged to
  stdout; only the output path is printed.

Environment variables:
  VOICE_INBOX_PATH         Local path where JSON files are saved.
                           Default: ~/storage/shared/voice_inbox/
  HARQIS_VOICE_SUBMIT_URL  Optional HTTP endpoint for direct submission.
                           If set, the file is also POSTed there.

Privacy:
  - Transcript text is never printed to stdout (only the output path is).
  - No location or notification data is included.
  - The JSON file is removed after server ingest (handled by ingest_voice_memos).

Termux / Android share flow:
  1. Dictate or paste your voice memo transcript in any notes app.
  2. Share the text to Termux (Android share sheet -> Termux).
     Termux receives the shared text as the $text intent variable; configure
     a .shortcuts/ entry or a Tasker task to run:
       python ~/harqis/voice_sender.py --text "$text"
  3. ingest_voice_memos.delay() on the server picks it up on the next run.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

_DEFAULT_INBOX = Path.home() / "storage" / "shared" / "voice_inbox"


def _read_clipboard() -> str:
    """Read text from the Android clipboard via termux-clipboard-get."""
    try:
        result = subprocess.run(
            ["termux-clipboard-get"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception as exc:
        print("[voice_sender] clipboard read failed: " + str(exc), file=sys.stderr)
        return ""


def _resolve_inbox() -> Path:
    env_path = os.environ.get("VOICE_INBOX_PATH", "").strip()
    return Path(env_path).resolve() if env_path else _DEFAULT_INBOX


def build_payload(
    transcript: str,
    *,
    recorded_at: datetime,
    duration_seconds: int = 0,
    filename: str = "",
    platform: str = "android",
) -> dict:
    """Build the JSON payload dict for the voice inbox contract."""
    return {
        "source": "voice_memo",
        "platform": platform,
        "recorded_at": recorded_at.strftime("%Y-%m-%dT%H:%M:%S"),
        "transcript": transcript.strip(),
        "duration_seconds": max(0, int(duration_seconds)),
        "filename": filename or "",
    }


def save_to_inbox(payload: dict, inbox_dir: Path) -> Path:
    """Save the payload to the inbox as a timestamped JSON file. Returns path."""
    inbox_dir.mkdir(parents=True, exist_ok=True)
    ts = payload["recorded_at"].replace(":", "").replace("-", "").replace("T", "_")
    dest = inbox_dir / ("voice_" + ts + ".json")
    if dest.exists():
        dest = inbox_dir / ("voice_" + ts + "_" + str(int(time.time())) + ".json")
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


def submit_to_server(payload: dict, url: str) -> bool:
    """POST the payload to a remote HTTP endpoint. Returns True on success."""
    try:
        import urllib.request
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status < 400
    except Exception as exc:
        print("[voice_sender] HTTP submit failed: " + str(exc), file=sys.stderr)
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Save an Android voice memo transcript to the harqis voice inbox."
    )
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--text", metavar="TRANSCRIPT",
                     help="Transcript text (passed directly, e.g. from share intent)")
    src.add_argument("--clipboard", action="store_true",
                     help="Read transcript from Android clipboard")
    parser.add_argument("--duration", type=int, default=0, metavar="SECONDS",
                        help="Audio duration in seconds (optional)")
    parser.add_argument("--filename", default="", metavar="NAME",
                        help="Source audio filename (optional, for context only)")
    args = parser.parse_args(argv)

    if args.text:
        transcript = args.text.strip()
    elif args.clipboard:
        transcript = _read_clipboard()
    else:
        transcript = sys.stdin.read().strip()

    if not transcript:
        print("[voice_sender] No transcript provided — nothing to save.", file=sys.stderr)
        return 1

    now = datetime.now()
    payload = build_payload(
        transcript,
        recorded_at=now,
        duration_seconds=args.duration,
        filename=args.filename,
    )

    inbox_dir = _resolve_inbox()
    dest = save_to_inbox(payload, inbox_dir)
    print("[voice_sender] saved -> " + str(dest))

    submit_url = os.environ.get("HARQIS_VOICE_SUBMIT_URL", "").strip()
    if submit_url:
        ok = submit_to_server(payload, submit_url)
        print("[voice_sender] HTTP submit: " + ("ok" if ok else "failed"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
