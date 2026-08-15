#!/usr/bin/env python
"""Snapshot and verify that a sibling HARQIS deployment was not disturbed."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SNAPSHOT = REPO_ROOT / ".harqis-data" / "isolation-baseline.json"


def _run(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"command failed ({' '.join(command)}): {detail}")
    return result.stdout


def docker_container_ids(project: str) -> list[str]:
    output = _run(
        [
            "docker",
            "ps",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--format",
            "{{.ID}}",
        ]
    )
    return sorted(line.strip() for line in output.splitlines() if line.strip())


def repo_processes(repo: Path) -> dict[str, str]:
    marker = str(repo.resolve()).replace("\\", "/").casefold()
    if sys.platform == "win32":
        escaped = str(repo.resolve()).replace("'", "''")
        output = _run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process | "
                f"Where-Object {{ $_.CommandLine -like '*{escaped}*' }} | "
                'ForEach-Object { "$($_.ProcessId)`t$($_.CommandLine)" }',
            ]
        )
    else:
        output = _run(["ps", "-axo", "pid=,command="])
    found: dict[str, str] = {}
    for line in output.splitlines():
        normalized = line.replace("\\", "/").casefold()
        if marker not in normalized:
            continue
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and parts[0].isdigit() and int(parts[0]) != os.getpid():
            found[parts[0]] = parts[1]
    return found


def capture(primary_project: str, primary_repo: Path) -> dict:
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "primary_project": primary_project,
        "primary_repo": str(primary_repo.resolve()),
        "container_ids": docker_container_ids(primary_project),
        "processes": repo_processes(primary_repo),
    }


def write_snapshot(path: Path, snapshot: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")


def verify(path: Path) -> list[str]:
    baseline = json.loads(path.read_text(encoding="utf-8"))
    current = capture(baseline["primary_project"], Path(baseline["primary_repo"]))
    failures: list[str] = []
    if baseline["container_ids"] != current["container_ids"]:
        failures.append("primary Compose container IDs changed")
    if baseline["processes"] != current["processes"]:
        failures.append("primary checkout process PIDs or command lines changed")
    return failures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("--primary-project", default="harqis-work")
    snapshot.add_argument("--primary-repo", type=Path, required=True)
    snapshot.add_argument("--output", type=Path, default=DEFAULT_SNAPSHOT)
    check = subparsers.add_parser("check")
    check.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "snapshot":
        write_snapshot(args.output, capture(args.primary_project, args.primary_repo))
        print(f"Isolation baseline written: {args.output}")
        return 0
    failures = verify(args.snapshot)
    if failures:
        print("Isolation check FAILED: " + "; ".join(failures), file=sys.stderr)
        return 1
    print("Isolation check passed: primary containers and processes are unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
