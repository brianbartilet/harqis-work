#!/usr/bin/env python3
"""
Re-authorize a HARQIS Google OAuth credential (default: GOOGLE_GMAIL_SEND).

Run interactively — this opens a browser for Google consent and writes a fresh
token into the credential's storage file under .env/. Use it when a daily job
starts failing with `invalid_grant: Token has been expired or revoked` (the
classic 7-day expiry of an OAuth app still in "Testing" publishing status).

Usage:
  python scripts/agents/diagnostics/reauth_gmail_send.py
  python scripts/agents/diagnostics/reauth_gmail_send.py --config GOOGLE_GMAIL_SEND
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _bootstrap_env() -> None:
    """Match the runtime env/config setup used by the daily jobs."""
    scripts_dir = REPO_ROOT / "scripts"
    for p in (REPO_ROOT, scripts_dir):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    from launch import setup_env  # type: ignore

    setup_env()
    os.environ.setdefault("PATH_APP_CONFIG", str(REPO_ROOT))
    os.environ.setdefault("PATH_APP_CONFIG_SECRETS", str(REPO_ROOT / ".env"))
    os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", default="GOOGLE_GMAIL_SEND",
                   help="apps_config.yaml credential id to re-authorize")
    p.add_argument("--keep-stale", action="store_true",
                   help="do not delete the existing token before the flow")
    args = p.parse_args(argv)

    _bootstrap_env()

    from apps.apps_config import CONFIG_MANAGER
    from apps.google_apps.references.web.client import GoogleApiClient

    cfg = CONFIG_MANAGER.get(args.config)
    scopes = cfg.app_data.get("scopes") or []
    credentials = cfg.app_data.get("credentials")
    storage = cfg.app_data.get("storage")

    secrets_dir = Path(os.environ["PATH_APP_CONFIG_SECRETS"])
    storage_path = secrets_dir / storage
    print(f"Re-authorizing {args.config}")
    print(f"  scopes:      {scopes}")
    print(f"  credentials: {secrets_dir / credentials}")
    print(f"  storage:     {storage_path}")

    client = GoogleApiClient(scopes_list=scopes, credentials=credentials, storage=storage)
    # A revoked refresh_token makes creds.refresh raise, which authorize() catches
    # and falls back to the browser flow. Dropping the stale file forces the flow
    # cleanly even if the token still parses as "valid".
    if not args.keep_stale and storage_path.exists():
        client.remove_storage()
        print("  removed stale token; starting fresh consent flow...")

    client.authorize()
    print(f"OK — fresh token written to {storage_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
