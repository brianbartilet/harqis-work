"""Stream the authenticated Second Brain feed in a terminal.

Usage:
    python scripts/second_brain_feed.py --url http://127.0.0.1:8080

Set SECOND_BRAIN_API_TOKEN to the shared, scoped Second Brain API token.
The token is read from the environment so it does not appear in process args.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _request(url: str, token: str, *, accept: str = "application/json"):
    return urllib.request.Request(
        url,
        headers={"Accept": accept, "Authorization": f"Bearer {token}"},
        method="GET",
    )


def print_snapshot(base_url: str, token: str) -> int:
    with urllib.request.urlopen(
        _request(base_url.rstrip("/") + "/second-brain/api/feed?client=cli", token),
        timeout=15,
    ) as response:
        payload = json.load(response)
    for item in payload.get("items") or []:
        print(f"[{str(item.get('category') or '').upper()}] {item.get('title') or ''}")
        if item.get("summary"):
            print(f"  {item['summary']}")
    return int(payload.get("cursor") or 0)


def stream(base_url: str, token: str) -> None:
    cursor = print_snapshot(base_url, token)
    url = base_url.rstrip("/") + f"/second-brain/api/events?cursor={cursor}"
    while True:
        try:
            with urllib.request.urlopen(_request(url, token, accept="text/event-stream"), timeout=90) as response:
                for raw in response:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if line.startswith("event: feed"):
                        cursor = print_snapshot(base_url, token)
                        url = base_url.rstrip("/") + f"/second-brain/api/events?cursor={cursor}"
        except (TimeoutError, urllib.error.URLError):
            continue


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stream the HARQIS Second Brain feed")
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--once", action="store_true", help="Print one snapshot and exit")
    args = parser.parse_args(argv)
    token = os.environ.get("SECOND_BRAIN_API_TOKEN", "").strip()
    if not token:
        parser.error("SECOND_BRAIN_API_TOKEN is required")
    if args.once:
        print_snapshot(args.url, token)
        return 0
    stream(args.url, token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
