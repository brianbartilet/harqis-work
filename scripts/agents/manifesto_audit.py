"""
scripts/agents/manifesto_audit.py

Validates that every Celery beat entry under `workflows/*/tasks_config.py`
carries the manifesto metadata block defined in docs/MANIFESTO.md and
documented in docs/thesis/MANIFESTO-REPO-UPDATES.md §4.2.

Hard violations (non-zero exit):
  - A task entry without a `'manifesto'` block.
  - A `code_role: 'capture'` task with `express_target` empty or 'none'.
  - A task missing a non-empty `review_artifact`.

Soft warnings (logged, exit code unaffected):
  - Unknown values for `code_role`, `para_bucket`.

Usage:
    python scripts/agents/manifesto_audit.py [--quiet]

Skips workflows whose `tasks_config.py` is empty (e.g. workflows/finance/
which is scaffolded but inactive).
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / "workflows"

# Ensure `from workflows.queues import WorkflowQueue` resolves when this script
# is run from anywhere — tasks_config files import the queues enum at module
# load time.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

VALID_CODE_ROLES: set[str] = {"capture", "organize", "distill", "express"}
VALID_PARA_BUCKETS: set[str] = {"project", "area", "resource", "archive"}

REQUIRED_FIELDS: tuple[str, ...] = (
    "code_role",
    "para_bucket",
    "express_target",
    "review_artifact",
    "hfl_signal",
)


def _load_tasks_config(path: Path) -> dict[str, Any]:
    """Load a tasks_config.py and return the first dict-of-tasks it defines."""
    spec = importlib.util.spec_from_file_location(
        f"_manifesto_audit.{path.parent.name}.tasks_config",
        path,
    )
    if not spec or not spec.loader:
        return {}
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for value in vars(mod).values():
        if (
            isinstance(value, dict)
            and value
            and all(isinstance(k, str) and k.startswith("run-job--") for k in value)
        ):
            return value
    return {}


def _split_roles(role_field: Any) -> list[str]:
    if not isinstance(role_field, str):
        return []
    return [r.strip() for r in role_field.split("+") if r.strip()]


def _audit_entry(workflow: str, key: str, entry: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (hard_violations, soft_warnings) for a single beat entry."""
    hard: list[str] = []
    soft: list[str] = []

    m = entry.get("manifesto")
    if not isinstance(m, dict):
        hard.append(f"{workflow}::{key}: missing 'manifesto' block")
        return hard, soft

    for field in REQUIRED_FIELDS:
        if field not in m:
            hard.append(f"{workflow}::{key}: manifesto.{field} missing")

    roles = _split_roles(m.get("code_role"))
    if not roles:
        hard.append(f"{workflow}::{key}: manifesto.code_role empty or malformed")
    else:
        for r in roles:
            if r not in VALID_CODE_ROLES:
                soft.append(
                    f"{workflow}::{key}: unknown code_role '{r}' "
                    f"(valid: {sorted(VALID_CODE_ROLES)})"
                )

    bucket = m.get("para_bucket")
    if isinstance(bucket, str) and bucket not in VALID_PARA_BUCKETS:
        soft.append(
            f"{workflow}::{key}: unknown para_bucket '{bucket}' "
            f"(valid: {sorted(VALID_PARA_BUCKETS)})"
        )

    express = m.get("express_target")
    if "capture" in roles and (not express or express == "none"):
        hard.append(
            f"{workflow}::{key}: capture task has no express_target — "
            f"manifesto rule: captures without an Express path are dead weight"
        )

    review = m.get("review_artifact")
    if not review:
        hard.append(f"{workflow}::{key}: manifesto.review_artifact empty (PAER violation)")

    return hard, soft


def _iter_active_configs() -> Iterable[tuple[str, Path]]:
    """Yield (workflow_name, tasks_config_path) for every non-empty tasks_config.py."""
    for p in sorted(WORKFLOWS_DIR.glob("*/tasks_config.py")):
        if p.parent.name.startswith("."):
            continue
        if p.stat().st_size == 0:
            continue
        yield p.parent.name, p


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit workflows/ against the manifesto.")
    parser.add_argument("--quiet", action="store_true", help="Only print violations.")
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Force-audit workflows/hfl/ even if filtered out. (No-op now that hfl "
             "is active and picked up by the default sweep; kept for any future "
             "scaffolded-but-empty workflow.)",
    )
    args = parser.parse_args()

    workflows_to_audit: list[tuple[str, Path]] = list(_iter_active_configs())
    if args.include_inactive:
        hfl_path = WORKFLOWS_DIR / "hfl" / "tasks_config.py"
        if hfl_path.exists() and ("hfl", hfl_path) not in workflows_to_audit:
            workflows_to_audit.append(("hfl", hfl_path))

    all_hard: list[str] = []
    all_soft: list[str] = []
    total_entries = 0

    for name, path in workflows_to_audit:
        config = _load_tasks_config(path)
        if not config:
            if not args.quiet:
                print(f"  - {name}: (no run-job entries — skipped)")
            continue
        if not args.quiet:
            print(f"  - {name}: {len(config)} entries")
        total_entries += len(config)
        for key, entry in config.items():
            hard, soft = _audit_entry(name, key, entry)
            all_hard.extend(hard)
            all_soft.extend(soft)

    if all_soft:
        print("\nSoft warnings:")
        for w in all_soft:
            print(f"  WARN  {w}")

    if all_hard:
        print("\nHard violations:")
        for v in all_hard:
            print(f"  FAIL  {v}")
        print(
            f"\nManifesto audit: {len(all_hard)} hard violation(s), "
            f"{len(all_soft)} soft warning(s), {total_entries} entries audited."
        )
        return 1

    print(
        f"\nManifesto audit: 0 hard violations, {len(all_soft)} soft warning(s), "
        f"{total_entries} entries audited. OK."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
