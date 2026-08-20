#!/usr/bin/env python3
"""CLI entry point for the shared HFL Activity Radar skill."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "workflows").is_dir() and (parent / "scripts" / "deploy.py").is_file():
            return parent
    raise RuntimeError("Run this skill from a harqis-work checkout")


def _bootstrap() -> None:
    root = _repo_root()
    sys.path.insert(0, str(root))
    os.chdir(root)
    from scripts.deploy import load_env_into_os, load_machine_config, machine_env_vars
    load_env_into_os()
    os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")
    os.environ.setdefault("WORKFLOW_CONFIG", "workflows.config")
    os.environ.update(machine_env_vars(load_machine_config(None)))


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze recent HFL activity against relevant history")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--recent-hours", type=int, default=8)
    run.add_argument("--retrospective-days", type=int, default=90)
    run.add_argument("--query", default="")
    run.add_argument("--tag", action="append", default=[])
    run.add_argument("--source")
    run.add_argument("--context", default="")
    run.add_argument("--model", default="claude-haiku-4-5-20251001")
    run.add_argument("--save-to-hfl", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    feedback = sub.add_parser("feedback")
    feedback.add_argument("fingerprint")
    feedback.add_argument("status", choices=("useful", "dismissed", "resolved"))
    feedback.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    _bootstrap()
    from workflows.hfl.tasks.activity_radar import record_activity_radar_feedback, run_activity_radar

    if args.command == "feedback":
        result = record_activity_radar_feedback(args.fingerprint, args.status, dry_run=args.dry_run)
        print(json.dumps(result, indent=2))
        return 0
    result = run_activity_radar(
        recent_hours=args.recent_hours, retrospective_days=args.retrospective_days,
        query=args.query, tags=args.tag or None, source=args.source, context=args.context,
        model=args.model, notify=False, save_to_hfl=args.save_to_hfl, dry_run=args.dry_run,
    )
    print(result["text"])
    return 0 if result["status"] != "partial" else 2


if __name__ == "__main__":
    raise SystemExit(main())
