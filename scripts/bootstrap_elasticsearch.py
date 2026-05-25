#!/usr/bin/env python
"""scripts/bootstrap_elasticsearch.py

Idempotent single-node ES bootstrap for HARQIS-work.

Ensures indices matching 'harqis-*' and 'tcg-mp-*' are configured for
zero replicas, which is required when running a single Elasticsearch
node (the default for this stack). Without this, newly-created indices
default to 1 replica and stay permanently yellow/unassigned.

Safe to run repeatedly — every operation is idempotent:
  - PUT /_index_template covers new indices going forward
  - PUT /<index>/_settings patches replicas on existing indices

Usage:
    python scripts/bootstrap_elasticsearch.py          # live run
    python scripts/bootstrap_elasticsearch.py --dry-run

Env knobs (no hardcoded secrets):
    ES_HOST          base URL             (fallback: ELASTIC_HOST, then http://localhost:9200)
    ELASTIC_USER     HTTP basic-auth user (optional; security off by default)
    ELASTIC_PASSWORD HTTP basic-auth pass (optional)
    ES_WAIT_SECONDS  seconds to wait for ES ready (default: 30)
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

TEMPLATE_NAME = "harqis-single-node"
INDEX_PATTERNS = ["harqis-*", "tcg-mp-*"]
TEMPLATE_SETTINGS = {
    "index": {
        "number_of_replicas": "0",
        "number_of_shards": "1",
    }
}


def _es_base() -> str:
    return (
        os.environ.get("ES_HOST")
        or os.environ.get("ELASTIC_HOST")
        or "http://localhost:9200"
    ).rstrip("/")


def _auth_headers() -> dict[str, str]:
    user = os.environ.get("ELASTIC_USER", "")
    pw = os.environ.get("ELASTIC_PASSWORD", "")
    if user and pw:
        token = base64.b64encode(f"{user}:{pw}".encode()).decode()
        return {"Authorization": f"Basic {token}"}
    return {}


def _call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    """HTTP call to ES. Returns (status, parsed_json). Raises on network error."""
    url = _es_base() + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", **_auth_headers()}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def _wait_ready(timeout: int) -> bool:
    """Poll /_cluster/health until ES responds or timeout expires."""
    deadline = time.monotonic() + timeout
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            status, body = _call("GET", "/_cluster/health")
            if status < 500:
                print(
                    f"  ES ready (attempt {attempt}): "
                    f"status={body.get('status', '?')} "
                    f"cluster={body.get('cluster_name', '?')}"
                )
                return True
        except Exception:
            pass
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        print(f"  Waiting for ES (attempt {attempt}, {int(remaining)}s left)...")
        time.sleep(min(2.0, remaining))
    return False


def _matches_pattern(name: str, pattern: str) -> bool:
    return name.startswith(pattern[:-1]) if pattern.endswith("*") else name == pattern


def is_harqis_index(name: str) -> bool:
    """True if name matches our index patterns and is not a system index."""
    if name.startswith("."):
        return False
    return any(_matches_pattern(name, p) for p in INDEX_PATTERNS)


def _install_template(dry_run: bool) -> None:
    payload = {
        "index_patterns": INDEX_PATTERNS,
        "template": {"settings": TEMPLATE_SETTINGS},
        "priority": 100,
        "_meta": {
            "description": "HARQIS single-node: zero replicas, 1 shard",
            "managed_by": "scripts/bootstrap_elasticsearch.py",
        },
    }
    if dry_run:
        print(
            f"  [dry-run] PUT /_index_template/{TEMPLATE_NAME}\n"
            f"    patterns={INDEX_PATTERNS} "
            f"settings={json.dumps(TEMPLATE_SETTINGS['index'])}"
        )
        return
    status, body = _call("PUT", f"/_index_template/{TEMPLATE_NAME}", payload)
    if status in (200, 201):
        print(f"  Template '{TEMPLATE_NAME}': installed/updated")
    else:
        print(f"  WARNING: template install returned {status}: {body.get('error', body)}")


def _patch_replicas(dry_run: bool) -> None:
    """Set replicas=0 on all existing matching indices."""
    try:
        status, body = _call("GET", "/_cat/indices?h=index&format=json")
    except Exception as exc:
        print(f"  WARNING: could not list indices: {exc}")
        return
    if status != 200:
        print(f"  WARNING: /_cat/indices returned {status}")
        return

    all_indices = [
        e["index"]
        for e in (body if isinstance(body, list) else [])
        if isinstance(e, dict) and "index" in e
    ]
    targets = sorted(i for i in all_indices if is_harqis_index(i))

    if not targets:
        print("  No existing HARQIS indices to patch.")
        return

    settings = {"index": {"number_of_replicas": "0"}}
    for idx in targets:
        if dry_run:
            print(f"  [dry-run] PUT /{idx}/_settings {json.dumps(settings['index'])}")
            continue
        status, resp = _call("PUT", f"/{idx}/_settings", settings)
        if status == 200:
            print(f"  Patched replicas=0: {idx}")
        else:
            print(f"  WARNING: could not patch {idx}: {status} {resp.get('error', resp)}")


def bootstrap(*, dry_run: bool = False, wait_seconds: int | None = None) -> bool:
    """Run the full bootstrap. Returns True on success, False if ES unreachable."""
    timeout = wait_seconds if wait_seconds is not None else int(
        os.environ.get("ES_WAIT_SECONDS", "30")
    )
    suffix = " [dry-run]" if dry_run else ""
    print(f"[es-bootstrap] target={_es_base()}{suffix}")

    if not _wait_ready(timeout):
        print(
            f"  WARNING: ES not reachable after {timeout}s — "
            "bootstrap skipped; cluster may report yellow shards. "
            "Re-run: python scripts/bootstrap_elasticsearch.py"
        )
        return False

    _install_template(dry_run)
    _patch_replicas(dry_run)
    print("[es-bootstrap] done.")
    return True


def _load_env_file() -> None:
    """Load .env/apps.env without overriding existing shell vars (standalone use)."""
    env_file = REPO_ROOT / ".env" / "apps.env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        os.environ.setdefault(k, v)


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print what would change without applying anything",
    )
    p.add_argument(
        "--wait", type=int, default=None, metavar="SECONDS",
        help="Override ES_WAIT_SECONDS (default: 30)",
    )
    args = p.parse_args()
    _load_env_file()
    ok = bootstrap(dry_run=args.dry_run, wait_seconds=args.wait)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
