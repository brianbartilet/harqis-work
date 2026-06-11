#!/usr/bin/env python
"""Verify a PLAUD_TOKEN (or export-folder fallback) before the nightly ingest.

Read-only smoke check for the Plaud acquisition adapter: prints which backend
is active (cloud vs export folder) and how many recordings it can see in a
window. Does NOT transcribe, distil, write to the HFL corpus/ES, or archive —
it only lists, so it's safe to run any time.

Usage:
    python scripts/check_plaud_token.py                       # last 7 days
    python scripts/check_plaud_token.py --days 30
    python scripts/check_plaud_token.py --since 2026-06-01 --until 2026-06-09

Exit codes (CI / automation friendly):
    0  a backend is ready and the listing succeeded
    1  the acquisition call errored (e.g. bad credentials, api.plaud.ai down)
    2  no backend ready (no PLAUD_EMAIL+PLAUD_PASSWORD, PLAUD_TOKEN, or
       PLAUD_EXPORT_DIR configured)

Auth: set PLAUD_EMAIL + PLAUD_PASSWORD in .env/apps.env (preferred — the
      adapter mints and auto-refreshes its own ~300-day token; this script
      exercises that mint path and prints the expiry). Alternatively set a
      manual PLAUD_TOKEN (web.plaud.ai → DevTools → Console →
      `localStorage.getItem("tokenstr")`), which expires periodically. For
      non-US accounts the regional redirect is followed automatically; you can
      also pin PLAUD_API_BASE. No cloud auth? Use the PLAUD_EXPORT_DIR folder
      backend.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

# scripts/check_plaud_token.py → repo root is parents[1].
REPO_ROOT = Path(__file__).resolve().parents[1]

# Mirror mcp/server.py's bootstrap so `apps.*` imports + config resolution work
# whether run via deploy.py or directly from a shell.
load_dotenv(REPO_ROOT / ".env" / "apps.env")
import os  # noqa: E402  (after load_dotenv so APP_CONFIG_FILE can be defaulted)

os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Verify the Plaud token / backend.")
    p.add_argument("--days", type=int, default=7,
                   help="Look back this many days (default 7). Ignored if --since is given.")
    p.add_argument("--since", help='Inclusive lower bound "YYYY-MM-DD".')
    p.add_argument("--until", help='Inclusive upper bound "YYYY-MM-DD" (default today).')
    return p.parse_args()


def _window(args: argparse.Namespace) -> tuple[str, str]:
    until = datetime.fromisoformat(args.until).date() if args.until else datetime.now().date()
    if args.since:
        since = datetime.fromisoformat(args.since).date()
    else:
        since = until - timedelta(days=args.days)
    return (since.strftime("%Y-%m-%dT00:00:00"), until.strftime("%Y-%m-%dT23:59:59"))


def main() -> int:
    args = _parse_args()

    from apps.plaud.config import CONFIG
    from apps.plaud.references.adapter import build_adapter

    adapter = build_adapter(CONFIG)
    status = adapter.status
    print(f"Plaud backend status: cloud_ready={status['cloud_ready']} "
          f"folder_ready={status['folder_ready']} active={status['active']!r}")

    if not status.get("active"):
        print("\nNo acquisition backend ready. Set PLAUD_EMAIL+PLAUD_PASSWORD "
              "or PLAUD_TOKEN (cloud), or PLAUD_EXPORT_DIR (export folder) in "
              ".env/apps.env.", file=sys.stderr)
        return 2

    if status["active"] == "cloud":
        # Exercises the mint path when credentials are configured: a missing or
        # near-expiry cached token is re-minted right here.
        info = adapter.active_backend.token_info()
        line = f"Cloud auth: mode={info.get('mode')!r}"
        if info.get("expires_at"):
            line += f" token_expires={info['expires_at']}"
        if info.get("error"):
            line += f" error={info['error']!r}"
        print(line)

    since_iso, until_iso = _window(args)
    print(f"Listing recordings in [{since_iso} .. {until_iso}] via "
          f"{status['active']} backend ...\n")

    # Call the active backend DIRECTLY (not adapter.list_recordings, which falls
    # back to the folder on a cloud error) so a bad/expired token surfaces here
    # as a failure instead of being masked as "0 recordings".
    backend = adapter.active_backend
    try:
        recordings = backend.list_recordings(since=since_iso, until=until_iso) or []
    except Exception as exc:  # noqa: BLE001 - report cleanly, non-zero exit
        print(f"ERROR: {status['active']} acquisition failed "
              f"({type(exc).__name__}): {exc}", file=sys.stderr)
        if status["active"] == "cloud":
            print("The cloud path calls api.plaud.ai directly. Check "
                  "PLAUD_EMAIL/PLAUD_PASSWORD are correct (or, on the manual "
                  "path, re-grab PLAUD_TOKEN from web.plaud.ai), that you have "
                  "network access, and (non-US accounts) that PLAUD_API_BASE "
                  "is set. Or fall back to the PLAUD_EXPORT_DIR folder backend.",
                  file=sys.stderr)
        return 1

    print(f"Found {len(recordings)} recording(s).")
    if recordings:
        print(f"\n{'started_at':<21}  {'tx':<3}  {'origin':<7}  id / title")
        print("-" * 72)
        for r in recordings:
            tx = "yes" if r.has_transcript else "no"
            label = r.title or r.id or "(untitled)"
            print(f"{(r.started_at or '?'):<21}  {tx:<3}  "
                  f"{(r.origin or '?'):<7}  {label[:40]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
