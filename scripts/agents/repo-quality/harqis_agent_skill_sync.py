#!/usr/bin/env python3
"""Sync canonical HARQIS agent skills into Hermes mirrors and command aliases.

The source of truth is ``.agents/skills``. Generated Hermes skills are named
``harqis-<source-name>``; ``quick_commands`` keeps the original source names as
aliases. Quiet success is intentional for Hermes no-agent cron jobs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml


PREFIX = "harqis-"


@dataclass(frozen=True)
class SyncPaths:
    repo_root: Path
    source_root: Path
    dest_root: Path
    config_path: Path


def _default_repo_root() -> Path:
    cwd = Path.cwd().resolve()
    if (cwd / ".agents" / "skills").is_dir():
        return cwd
    candidate = Path(__file__).resolve().parents[3]
    if (candidate / ".agents" / "skills").is_dir():
        return candidate
    return Path("/Users/harqis-one/GIT/harqis-work")


def _paths(repo_root: Path, hermes_home: Path) -> SyncPaths:
    repo_root = repo_root.expanduser().resolve()
    hermes_home = hermes_home.expanduser().resolve()
    return SyncPaths(
        repo_root=repo_root,
        source_root=repo_root / ".agents" / "skills",
        dest_root=hermes_home / "skills" / "software-development",
        config_path=hermes_home / "config.yaml",
    )


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        match = re.search(r"\n---\s*\n", text[3:])
        if match:
            fm_text = text[3 : match.start() + 3]
            body = text[match.end() + 3 :]
            try:
                data = yaml.safe_load(fm_text) or {}
            except yaml.YAMLError:
                data = {}
            if isinstance(data, dict):
                return data, body
    return {}, text


def extract_description(text: str, frontmatter: dict) -> str:
    raw = frontmatter.get("description") if isinstance(frontmatter, dict) else None
    if isinstance(raw, str):
        description = " ".join(raw.split())
    else:
        description = ""
        in_frontmatter = text.startswith("---")
        frontmatter_closed = not in_frontmatter
        for index, line in enumerate(text.splitlines()):
            stripped = line.strip()
            if in_frontmatter and not frontmatter_closed:
                if index > 0 and stripped == "---":
                    frontmatter_closed = True
                continue
            if stripped and stripped != "---" and not stripped.startswith("#"):
                description = stripped
                break
        if not description:
            description = "HARQIS-work agent project skill."
    description = re.sub(r"\s+", " ", description).strip()
    if len(description) > 820:
        description = description[:817].rstrip() + "..."
    full = f"Use when working in HARQIS-work: {description}"
    return full[:1021].rstrip() + "..." if len(full) > 1024 else full


def title_from_name(name: str) -> str:
    return " ".join(part.capitalize() for part in name.split("-"))


def render_mirror(source_path: Path, repo_root: Path) -> tuple[str, str, str]:
    original_name = source_path.parent.name
    hermes_name = PREFIX + original_name
    source_text = source_path.read_text(encoding="utf-8")
    frontmatter, _body = parse_frontmatter(source_text)
    source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    relative_path = source_path.relative_to(repo_root)
    description = extract_description(source_text, frontmatter)

    content = f'''---
name: {hermes_name}
description: {json.dumps(description)}
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [harqis-work, agent-skill, mirrored-skill, {original_name}]
    related_skills: [harqis-work-context, claude-code, codex, opencode]
  harqis_work:
    source: {relative_path}
    source_sha256: {source_hash}
    original_name: {original_name}
---

# HARQIS Agent Skill Mirror: {title_from_name(original_name)}

This is a Hermes-loadable mirror of the HARQIS-work agent skill `{original_name}`.

Source: `{repo_root / relative_path}`
Source SHA-256: `{source_hash}`

Use this skill when Brian asks Hermes to perform the same HARQIS-work task normally covered by HARQIS agent skill `{original_name}`. The canonical source is repo-local `.agents/skills`; `.claude/skills` is only a generated compatibility copy for Claude Code.

---

{source_text.rstrip()}
'''
    return hermes_name, source_hash, content


def validate_skill_content(content: str) -> list[str]:
    errors: list[str] = []
    if not content.startswith("---"):
        errors.append("missing opening frontmatter")
    match = re.search(r"\n---\s*\n", content[3:])
    if not match:
        errors.append("missing closing frontmatter")
        return errors
    fm_text = content[3 : match.start() + 3]
    try:
        data = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        errors.append(f"invalid yaml frontmatter: {exc}")
        return errors
    if not isinstance(data, dict):
        errors.append("frontmatter is not a mapping")
        return errors
    if not data.get("name"):
        errors.append("missing name")
    description = data.get("description")
    if not description:
        errors.append("missing description")
    elif len(str(description)) > 1024:
        errors.append("description longer than 1024 chars")
    if len(content) > 100_000:
        errors.append("content longer than 100000 chars")
    if not content[match.end() + 3 :].strip():
        errors.append("empty body")
    return errors


def _replace_top_level_mapping(text: str, key: str, value: dict) -> str:
    rendered = yaml.safe_dump(
        {key: value},
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).rstrip() + "\n"
    lines = text.splitlines(keepends=True)
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if re.match(rf"^{re.escape(key)}\s*:", line)
        ),
        None,
    )
    if start is None:
        separator = "" if not text or text.endswith("\n") else "\n"
        return text + separator + rendered

    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.strip() and not line.startswith((" ", "\t", "#")):
            end = index
            break
    return "".join(lines[:start]) + rendered + "".join(lines[end:])


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode if path.exists() else 0o600
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def sync_quick_commands(
    config_path: Path,
    expected_aliases: dict[str, str],
    *,
    check_only: bool = False,
) -> dict[str, list[str]]:
    text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    parsed = yaml.safe_load(text) or {}
    if not isinstance(parsed, dict):
        raise ValueError(f"Hermes config is not a YAML mapping: {config_path}")
    quick_commands = parsed.get("quick_commands") or {}
    if not isinstance(quick_commands, dict):
        raise ValueError(f"quick_commands is not a YAML mapping: {config_path}")

    created: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []
    desired_commands = dict(quick_commands)
    for original_name, target in sorted(expected_aliases.items()):
        desired = {"type": "alias", "target": target}
        current = quick_commands.get(original_name)
        if current is None:
            created.append(original_name)
        elif current != desired:
            updated.append(original_name)
        else:
            unchanged.append(original_name)
        desired_commands[original_name] = desired

    if (created or updated) and not check_only:
        updated_text = _replace_top_level_mapping(text, "quick_commands", desired_commands)
        reparsed = yaml.safe_load(updated_text) or {}
        if not isinstance(reparsed.get("quick_commands"), dict):
            raise ValueError("generated quick_commands block is invalid")
        _atomic_write(config_path, updated_text)

    return {"created": created, "updated": updated, "unchanged": unchanged}


def sync(paths: SyncPaths, *, check_only: bool = False) -> tuple[dict, bool]:
    sources = sorted(paths.source_root.glob("*/SKILL.md"))
    if not sources:
        raise ValueError(f"no skills found under {paths.source_root}")

    if not check_only:
        paths.dest_root.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []
    validation_errors: dict[str, list[str]] = {}
    source_names: set[str] = set()
    aliases: dict[str, str] = {}

    for source_path in sources:
        hermes_name, _source_hash, content = render_mirror(source_path, paths.repo_root)
        source_names.add(hermes_name)
        aliases[source_path.parent.name] = hermes_name
        errors = validate_skill_content(content)
        if errors:
            validation_errors[hermes_name] = errors
            continue
        destination = paths.dest_root / hermes_name / "SKILL.md"
        old = destination.read_text(encoding="utf-8") if destination.exists() else None
        if old == content:
            unchanged.append(hermes_name)
        elif old is None:
            created.append(hermes_name)
            if not check_only:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding="utf-8")
        else:
            updated.append(hermes_name)
            if not check_only:
                destination.write_text(content, encoding="utf-8")

    existing_mirrors: set[str] = set()
    for existing in paths.dest_root.glob(f"{PREFIX}*/SKILL.md"):
        existing_text = existing.read_text(encoding="utf-8")
        if "harqis_work:" in existing_text and "source_sha256:" in existing_text and (
            ".claude/skills/" in existing_text or ".agents/skills/" in existing_text
        ):
            existing_mirrors.add(existing.parent.name)
    stale = sorted(existing_mirrors - source_names)

    alias_result = sync_quick_commands(
        paths.config_path,
        aliases,
        check_only=check_only or bool(validation_errors),
    )
    result = {
        "success": not validation_errors,
        "source_root": str(paths.source_root),
        "dest_root": str(paths.dest_root),
        "config_path": str(paths.config_path),
        "source_count": len(sources),
        "mirror_count": len(existing_mirrors | source_names),
        "created": created,
        "updated": updated,
        "unchanged_count": len(unchanged),
        "stale_mirrors": stale,
        "validation_errors": validation_errors,
        "aliases": alias_result,
    }
    has_delta = bool(
        created
        or updated
        or stale
        or validation_errors
        or alias_result["created"]
        or alias_result["updated"]
    )
    return result, has_delta


def _print_result(result: dict, *, check_only: bool) -> None:
    if result["validation_errors"]:
        print("HARQIS agent→Hermes skill sync failed validation.")
    elif check_only:
        print("HARQIS agent→Hermes skill sync check found drift.")
    else:
        print("HARQIS agent→Hermes skill sync changed local state.")
    print()
    print(f'- Source agent skills: {result["source_count"]}')
    print(f'- Generated Hermes mirrors: {result["mirror_count"]}')
    if result["created"]:
        print(f'- Created mirrors: {", ".join(result["created"])}')
    if result["updated"]:
        print(f'- Updated mirrors: {", ".join(result["updated"])}')
    if result["stale_mirrors"]:
        print(f'- Stale mirrors: {", ".join(result["stale_mirrors"])}')
    if result["aliases"]["created"]:
        print(f'- Created aliases: {", ".join(result["aliases"]["created"])}')
    if result["aliases"]["updated"]:
        print(f'- Updated aliases: {", ".join(result["aliases"]["updated"])}')
    if result["validation_errors"]:
        print("- Validation errors:")
        for name, errors in sorted(result["validation_errors"].items()):
            print(f'  - {name}: {"; ".join(errors)}')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=_default_repo_root())
    parser.add_argument(
        "--hermes-home",
        type=Path,
        default=Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser(),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report mirror or alias drift without writing",
    )
    args = parser.parse_args()

    try:
        result, has_delta = sync(
            _paths(args.repo_root, args.hermes_home),
            check_only=args.check,
        )
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"HARQIS agent→Hermes skill sync failed: {exc}")
        return 1

    if not has_delta:
        return 0
    _print_result(result, check_only=args.check)
    if result["validation_errors"] or args.check:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
