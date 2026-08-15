"""CLI wrapper for apps.git.fleet."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.git.fleet import (  # noqa: E402
    FleetError,
    cherry_pick_to_worktree,
    deploy_fork,
    load_latest_report,
    run_fork_tests,
    scan_fleet,
)


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def _bootstrap_harqis_environment() -> None:
    """Load machine-aware config before importing workflows.* for HFL writes."""
    import os

    from scripts.deploy import load_env_into_os, load_machine_config, machine_env_vars

    load_env_into_os()
    os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")
    os.environ.setdefault("WORKFLOW_CONFIG", "workflows.config")
    os.environ.update(machine_env_vars(load_machine_config(None)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage harqis-work fork drift and synchronization")
    parser.add_argument("--config", default=str(REPO_ROOT / "fork-fleet.toml"))
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="Discover and compare every managed fork")
    scan.add_argument("--hfl", action="store_true", help="write per-fork and fleet HFL entries")
    sub.add_parser("show", help="show the latest persisted report")

    sync = sub.add_parser("sync", help="cherry-pick commits in an isolated worktree")
    sync.add_argument("--repository", required=True)
    sync.add_argument("--branch", required=True)
    sync.add_argument("--commit", action="append", required=True, dest="commits")
    sync.add_argument("--test-path", action="append", default=[])
    sync.add_argument("--skip-tests", action="store_true")
    sync.add_argument("--publish-pr", action="store_true")
    sync.add_argument("--pr-title", default="")
    sync.add_argument("--pr-body", default="")

    test = sub.add_parser("test", help="run fork regression tests in an isolated worktree")
    test.add_argument("--repository", required=True)
    test.add_argument("--branch", default="main")
    test.add_argument("--test-path", action="append", default=[])

    deploy = sub.add_parser("deploy", help="deploy a fork branch from an isolated worktree")
    deploy.add_argument("--repository", required=True)
    deploy.add_argument("--branch", required=True)
    deploy.add_argument("--role", choices=("host", "worker"), default="host")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "scan":
            report = scan_fleet(config_path=args.config)
            if args.hfl:
                _bootstrap_harqis_environment()
                from workflows.git_forks.hfl import persist_scan_entries
                report["hfl"] = persist_scan_entries(report)
            _print(report)
        elif args.command == "show":
            _print(load_latest_report(args.config))
        elif args.command == "sync":
            _print(cherry_pick_to_worktree(
                args.repository, args.commits, branch=args.branch,
                run_tests=not args.skip_tests, test_paths=args.test_path,
                publish_pr=args.publish_pr, pr_title=args.pr_title,
                pr_body=args.pr_body, config_path=args.config,
            ))
        elif args.command == "test":
            _print(run_fork_tests(
                args.repository, branch=args.branch,
                test_paths=args.test_path, config_path=args.config,
            ))
        elif args.command == "deploy":
            _print(deploy_fork(
                args.repository, branch=args.branch, role=args.role,
                config_path=args.config,
            ))
        return 0
    except (FleetError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
