#!/usr/bin/env python3
"""CLI entry point for the HFL activity-corpus source health skill."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "workflows" / "hfl").is_dir() and (parent / "scripts" / "deploy.py").is_file():
            return parent
    raise RuntimeError("Run this skill from a harqis-work checkout")


def _bootstrap() -> Path:
    root = _repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.chdir(root)
    from scripts.deploy import load_env_into_os, load_machine_config, machine_env_vars

    load_env_into_os()
    os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")
    os.environ.setdefault("WORKFLOW_CONFIG", "workflows.config")
    os.environ.update(machine_env_vars(load_machine_config(None)))
    return root


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check HFL source task, corpus, Elasticsearch, and upstream freshness"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan")
    scan.add_argument("--mode", choices=("daily", "weekly"), default="daily")
    scan.add_argument("--write-report", action="store_true")
    scan.add_argument("--save-to-hfl", action="store_true")
    scan.add_argument("--notify", action="store_true")
    scan.add_argument("--dry-run", action="store_true")
    scan.add_argument("--json", action="store_true")
    policy = sub.add_parser("policy")
    policy.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    # Several legacy config loaders print startup notices. Keep stdout clean so
    # --json remains machine-readable while retaining those notices on stderr.
    with contextlib.redirect_stdout(sys.stderr):
        _bootstrap()
        from workflows.hfl.source_health import (
            load_source_registry,
            render_failure_report,
            scan_activity_corpus_sources,
        )
        from workflows.hfl.tasks.check_activity_corpus_sources import (
            run_activity_corpus_source_check,
        )

    if args.command == "policy":
        settings, policies = load_source_registry()
        payload = {
            "settings": settings,
            "sources": [
                {
                    "key": item.key,
                    "mode": item.monitor_mode,
                    "schedule": item.schedule,
                    "task": item.task,
                    "related_tasks": list(item.related_tasks),
                    "entry_sources": list(item.entry_sources),
                    "auto_retry": item.auto_retry,
                    "backfill": item.backfill,
                }
                for item in policies
            ],
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Sources: {len(policies)}; max backfill: {settings.get('max_backfill_days', 15)} days")
            for item in policies:
                print(f"- {item.key}: {item.monitor_mode}; {item.schedule}")
        return 0

    mutating = args.write_report or args.save_to_hfl or args.notify
    if mutating:
        result = run_activity_corpus_source_check(
            mode=args.mode,
            write_report=args.write_report,
            save_to_hfl=args.save_to_hfl,
            notify=args.notify,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "healthy" else 2

    snapshot = scan_activity_corpus_sources(mode=args.mode)
    if args.json:
        print(json.dumps(snapshot.to_dict(), indent=2))
    elif snapshot.failures or snapshot.registry_errors:
        print(render_failure_report(snapshot))
    else:
        print("No HFL activity-corpus source failures.")
    return 0 if snapshot.status == "healthy" else 2


if __name__ == "__main__":
    raise SystemExit(main())
