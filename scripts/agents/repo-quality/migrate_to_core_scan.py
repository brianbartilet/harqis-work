#!/usr/bin/env python3
"""
scripts/agents/repo-quality/migrate_to_core_scan.py

Deterministic harvest-candidate scan for the `/migrate-to-core` skill.

Walks harqis-work for code that could move *upstream* into harqis-core (the
generic ``core`` package), scores each candidate by "genericness", and maps what
already exists upstream so the skill never proposes a duplicate. The skill
(Claude) reads this JSON and does the judgment + paired-PR authoring — this
script ships no opinions of its own beyond the coupling signals.

Harvest sources (relative to the repo root):
  - ``apps/<name>/``       — service-app integrations + the ``apps/.template`` scaffold
  - ``scripts/agents/*.py``— agent-support helpers

Hard exclusions (never harvested):
  - ``workflows/``         — service/chaining-specific (the skill's charter excludes it)
  - ``apps/antropic``      — AI/Claude scaffold (harqis-core deliberately keeps AI here)
  - ``**/tests/**``        — tests travel with their module, not on their own

Per-candidate coupling signals (these drive the genericness judgment):
  - ``core_imports``    : imports from ``core.`` — already builds on harqis-core (good)
  - ``repo_couplings``  : imports from ``workflows.`` / ``agents.`` / other ``apps.`` (bad)
  - ``sprout_coupled``  : uses ``core.apps.sprout`` (a Celery task → workflow-coupled, reject)
  - ``external_deps``   : third-party packages it pulls in (must exist in core too)
  - ``already_upstream``: a module with the same leaf name already lives under ``core/``

Usage:
    python scripts/agents/repo-quality/migrate_to_core_scan.py [--core-path DIR]
        [--json-out PATH] [--quiet]

Resolves harqis-core from ``--core-path``, ``$HARQIS_CORE_PATH``, a repo sibling,
or ``~/GIT/harqis-core``. Writes the report to
``<repo>/.harqis-data/migrate_to_core_scan.json`` and prints a ranked summary.
Always exits 0 — a scan is informational.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / ".harqis-data"

SCAN_DIRS = ("apps", "scripts/agents")
EXCLUDE_PARTS = {"tests", "__pycache__", ".pytest_cache", ".venv"}
EXCLUDE_APPS = {"antropic"}      # AI scaffold stays in harqis-work (per the skill charter)
EXCLUDE_TOP = {"workflows"}      # service/chaining — never harvested


# ── harqis-core location + upstream map ───────────────────────────────────────

def resolve_core_path(explicit: Optional[str]) -> Optional[Path]:
    """First reachable harqis-core checkout (one that contains a ``core/`` dir)."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env = os.environ.get("HARQIS_CORE_PATH", "").strip()
    if env:
        candidates.append(Path(env).expanduser())
    candidates += [REPO_ROOT.parent / "harqis-core", Path.home() / "GIT" / "harqis-core"]
    for c in candidates:
        if (c / "core").is_dir():
            return c
    return None


def map_core(core_path: Path) -> dict:
    """Top-level ``core/`` subpackages + the set of module leaf-names already
    upstream (for duplicate detection)."""
    core_dir = core_path / "core"
    subpackages = sorted(
        p.name for p in core_dir.iterdir()
        if p.is_dir() and p.name not in EXCLUDE_PARTS and not p.name.startswith(".")
    )
    leaves: set[str] = set()
    for py in core_dir.rglob("*.py"):
        if any(part in EXCLUDE_PARTS for part in py.parts):
            continue
        leaves.add(py.stem)
    return {"subpackages": subpackages, "module_leaves": sorted(leaves)}


# ── import analysis ───────────────────────────────────────────────────────────

def _imports(py: Path) -> list[str]:
    """Absolute import module strings in a .py file (best-effort via AST)."""
    try:
        tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError, ValueError):
        return []
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.append(node.module)
    return mods


_STDLIB_PREFIXES = (
    "os", "sys", "re", "json", "math", "time", "datetime", "pathlib", "typing",
    "dataclasses", "collections", "functools", "itertools", "subprocess", "ast",
    "logging", "argparse", "base64", "hashlib", "abc", "enum", "io", "contextlib",
    "tempfile", "shutil", "sqlite3", "urllib", "socket", "calendar", "random",
    "string", "uuid", "warnings", "__future__", "threading", "asyncio", "csv",
)
_LOCAL_PREFIXES = ("apps", "workflows", "agents", "scripts", "frontend", "mcp")


def _classify_imports(mods: list[str], self_top: str) -> dict:
    core_imports, repo_couplings, external_deps = set(), set(), set()
    for m in mods:
        head = m.split(".", 1)[0]
        if head == "core":
            core_imports.add(".".join(m.split(".")[:3]))
        elif head in _LOCAL_PREFIXES:
            # An import of the candidate's own package is not a coupling.
            if not m.startswith(self_top):
                repo_couplings.add(".".join(m.split(".")[:2]))
        elif head in _STDLIB_PREFIXES:
            continue
        else:
            external_deps.add(head)
    return {
        "core_imports": sorted(core_imports),
        "repo_couplings": sorted(repo_couplings),
        "external_deps": sorted(external_deps),
        "sprout_coupled": any(m.startswith("core.apps.sprout") for m in mods),
    }


# ── candidate model ───────────────────────────────────────────────────────────

@dataclass
class Candidate:
    name: str
    kind: str                       # "app" | "agent-script"
    path: str                       # repo-relative
    loc: int = 0
    files: int = 0
    core_imports: list[str] = field(default_factory=list)
    repo_couplings: list[str] = field(default_factory=list)
    external_deps: list[str] = field(default_factory=list)
    sprout_coupled: bool = False
    already_upstream: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    recommendation: str = "review"  # "candidate" | "coupled" | "review"


def _aggregate(py_files: list[Path], self_top: str) -> dict:
    mods: list[str] = []
    loc = 0
    for py in py_files:
        mods += _imports(py)
        try:
            loc += sum(1 for _ in py.open("r", encoding="utf-8", errors="replace"))
        except OSError:
            pass
    agg = _classify_imports(mods, self_top)
    agg["loc"] = loc
    return agg


def _finalize(c: Candidate, core_leaves: set[str]) -> Candidate:
    leaf = Path(c.path).name
    c.already_upstream = sorted({n for n in (leaf, c.name) if n in core_leaves})

    # `apps.config_loader` is harqis-work's thin config shim over core's webservice
    # config — a coupling that's liftable (swap the shim for core's loader). Any
    # OTHER repo import (workflows/mcp/agents/another app) is a hard coupling.
    hard_couplings = [m for m in c.repo_couplings if m != "apps.config_loader"]
    shim_only = c.repo_couplings == ["apps.config_loader"]

    if hard_couplings:
        c.flags.append("repo-coupled")
    if shim_only:
        c.flags.append("config-shim-only")
    if c.sprout_coupled:
        c.flags.append("celery-task")
    if c.already_upstream:
        c.flags.append("maybe-upstream")
    if c.core_imports and not hard_couplings and not c.sprout_coupled:
        c.flags.append("builds-on-core")

    if c.sprout_coupled or hard_couplings:
        c.recommendation = "coupled"        # workflow/mcp/app-coupled → decouple first
    else:
        c.recommendation = "candidate"      # self-contained or shim-only → harvest-worthy
    return c


# ── scan ──────────────────────────────────────────────────────────────────────

def scan(core_path: Optional[Path]) -> dict:
    core = map_core(core_path) if core_path else {"subpackages": [], "module_leaves": []}
    core_leaves = set(core["module_leaves"])
    candidates: list[Candidate] = []
    excluded: list[str] = []

    apps_dir = REPO_ROOT / "apps"
    if apps_dir.is_dir():
        for app in sorted(p for p in apps_dir.iterdir() if p.is_dir()):
            if app.name in EXCLUDE_APPS:
                excluded.append(f"apps/{app.name} (AI scaffold — stays in harqis-work)")
                continue
            if app.name.startswith("__"):
                continue
            py_files = [
                p for p in app.rglob("*.py")
                if not any(part in EXCLUDE_PARTS for part in p.parts)
            ]
            if not py_files:
                continue
            agg = _aggregate(py_files, self_top=f"apps.{app.name.lstrip('.')}")
            candidates.append(_finalize(Candidate(
                name=app.name, kind="app", path=f"apps/{app.name}",
                loc=agg["loc"], files=len(py_files),
                core_imports=agg["core_imports"], repo_couplings=agg["repo_couplings"],
                external_deps=agg["external_deps"], sprout_coupled=agg["sprout_coupled"],
            ), core_leaves))

    agents_dir = REPO_ROOT / "scripts" / "agents"
    if agents_dir.is_dir():
        for py in sorted(agents_dir.glob("*.py")):
            agg = _aggregate([py], self_top="scripts.agents")
            candidates.append(_finalize(Candidate(
                name=py.stem, kind="agent-script", path=f"scripts/agents/{py.name}",
                loc=agg["loc"], files=1,
                core_imports=agg["core_imports"], repo_couplings=agg["repo_couplings"],
                external_deps=agg["external_deps"], sprout_coupled=agg["sprout_coupled"],
            ), core_leaves))

    # Rank: harvest-worthy first, then by least coupling / smallest surface.
    order = {"candidate": 0, "coupled": 1}
    candidates.sort(key=lambda c: (order[c.recommendation], len(c.repo_couplings), c.loc))

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "harqis_core_path": str(core_path) if core_path else None,
        "harqis_core": core,
        "excluded": excluded,
        "counts": {
            "candidates": sum(1 for c in candidates if c.recommendation == "candidate"),
            "coupled": sum(1 for c in candidates if c.recommendation == "coupled"),
            "total": len(candidates),
        },
        "candidates": [asdict(c) for c in candidates],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--core-path", help="Path to the harqis-core checkout.")
    ap.add_argument("--json-out", help="Where to write the report JSON.")
    ap.add_argument("--quiet", action="store_true", help="Suppress the summary print.")
    args = ap.parse_args()

    core_path = resolve_core_path(args.core_path)
    report = scan(core_path)

    out = Path(args.json_out) if args.json_out else DATA_DIR / "migrate_to_core_scan.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if not args.quiet:
        c = report["counts"]
        print(f"harqis-core: {report['harqis_core_path'] or 'NOT FOUND'}")
        print(f"candidates={c['candidates']} coupled={c['coupled']} (total {c['total']})")
        print(f"report -> {out}")
        for cand in report["candidates"]:
            if cand["recommendation"] == "candidate":
                print(f"  [candidate] {cand['path']}  loc={cand['loc']} "
                      f"core={len(cand['core_imports'])} ext={cand['external_deps']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
