"""CLI wrapper for apps.git.fleet."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _bootstrap_harqis_environment() -> None:
    """Load machine-aware config before importing apps.* or workflows.*."""
    import os

    from scripts.deploy import load_env_into_os, load_machine_config, machine_env_vars

    load_env_into_os()
    os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")
    os.environ.setdefault("WORKFLOW_CONFIG", "workflows.config")
    os.environ.update(machine_env_vars(load_machine_config(None)))


_bootstrap_harqis_environment()

from apps.git.fleet import (  # noqa: E402
    FleetError,
    cherry_pick_to_worktree,
    deploy_fork,
    load_latest_report,
    plan_feature_shipping,
    promote_feature_pull_request,
    run_fork_tests,
    scan_fleet,
    ship_feature_plan,
)


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


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

    plan = sub.add_parser("plan", help="plan candidate feature compatibility across the fleet")
    source = plan.add_mutually_exclusive_group(required=True)
    source.add_argument("--commit", action="append", dest="commits")
    source.add_argument("--range", dest="commit_range", default="")
    source.add_argument("--pull-request", default="")
    plan.add_argument("--include", action="append", default=[])
    plan.add_argument("--exclude", action="append", default=[])
    plan.add_argument("--squash", action="store_true")

    ship = sub.add_parser("ship", help="execute an explicitly approved persisted feature plan")
    ship.add_argument("--plan", required=True, help="plan id or persisted plan JSON path")
    ship.add_argument("--approve", required=True, help="must exactly match the plan id")
    ship.add_argument("--repository", action="append", default=[])
    ship.add_argument("--test-path", action="append", default=[])
    ship.add_argument("--deploy", action="append", default=[], metavar="REPOSITORY=ROLE")
    ship.add_argument("--direct-main", action="append", default=[])
    ship.add_argument("--confirm-direct-main", default="")
    ship.add_argument("--skip-hfl", action="store_true")

    promote = sub.add_parser("promote", help="mark a draft fleet PR ready after successful GitHub checks")
    promote.add_argument("--repository", required=True)
    promote.add_argument("--pull-request", required=True, type=int)
    promote.add_argument("--approve", required=True)
    return parser


def _deploy_roles(values: list[str]) -> dict[str, str]:
    roles = {}
    for value in values:
        if "=" not in value:
            raise ValueError("--deploy must use REPOSITORY=host or REPOSITORY=worker")
        repository, role = value.rsplit("=", 1)
        if not repository or role not in {"host", "worker"}:
            raise ValueError("--deploy must use REPOSITORY=host or REPOSITORY=worker")
        roles[repository] = role
    return roles


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
        elif args.command == "plan":
            _print(plan_feature_shipping(
                commits=args.commits or (), commit_range=args.commit_range,
                pull_request=args.pull_request, include=args.include,
                exclude=args.exclude, squash=args.squash, config_path=args.config,
            ))
        elif args.command == "ship":
            report = ship_feature_plan(
                args.plan, approval=args.approve, repositories=args.repository,
                test_paths=args.test_path, deploy_roles=_deploy_roles(args.deploy),
                direct_main=args.direct_main,
                direct_main_confirmation=args.confirm_direct_main,
                config_path=args.config,
            )
            if not args.skip_hfl:
                _bootstrap_harqis_environment()
                from workflows.git_forks.hfl import persist_rollout_entries
                report["hfl"] = persist_rollout_entries(report)
            _print(report)
        elif args.command == "promote":
            _print(promote_feature_pull_request(
                args.repository, args.pull_request, approval=args.approve,
            ))
        return 0
    except (FleetError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
