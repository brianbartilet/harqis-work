"""Machine-scoped configuration for repository-backed notes.

Canonical repository metadata lives under ``[notes.repositories.<name>]``.
Each editing machine binds a repository name to its local checkout under
``[<machine>.notes.repositories]``. Host checkouts and state stay outside the
source repositories so synchronization never writes HARQIS metadata into notes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from workflows.dumps.config import (
    HARQIS_SERVER_MACHINE_NAME,
    REPO_ROOT,
    load_merged_config,
    resolve_local_machine_name,
)


@dataclass(frozen=True)
class NoteRepository:
    name: str
    remote: str
    branch: str
    host_path: Path
    tags: tuple[str, ...]
    include_globs: tuple[str, ...]
    exclude_globs: tuple[str, ...]
    max_entries: int
    max_media: int
    max_text_chars: int
    max_topics_per_note: int
    remote_name: str = "origin"


@dataclass(frozen=True)
class LocalNoteRepository:
    definition: NoteRepository
    source_path: Path


def _as_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def get_notes_state_dir(cfg: dict | None = None) -> Path:
    cfg = cfg if cfg is not None else load_merged_config()
    raw = str((cfg.get("notes", {}) or {}).get("state_dir", "")).strip()
    return Path(raw).expanduser() if raw else REPO_ROOT / "logs" / "notes"


def get_note_repositories(cfg: dict | None = None) -> dict[str, NoteRepository]:
    cfg = cfg if cfg is not None else load_merged_config()
    raw_repos = (cfg.get("notes", {}) or {}).get("repositories", {}) or {}
    repositories: dict[str, NoteRepository] = {}
    for name, raw in raw_repos.items():
        if not isinstance(raw, dict) or raw.get("enabled") is False:
            continue
        remote = str(raw.get("remote", "")).strip()
        host_path = str(raw.get("host_path", "")).strip()
        if not remote or not host_path:
            continue
        base_tags = _as_tuple(raw.get("tags")) or ("notes", "dsm")
        repositories[str(name)] = NoteRepository(
            name=str(name),
            remote=remote,
            branch=str(raw.get("branch", "main")).strip() or "main",
            host_path=Path(host_path).expanduser(),
            tags=base_tags,
            include_globs=_as_tuple(raw.get("include_globs")),
            exclude_globs=_as_tuple(raw.get("exclude_globs")),
            max_entries=max(1, int(raw.get("max_entries", 25))),
            max_media=max(0, int(raw.get("max_media", 10))),
            max_text_chars=max(1000, int(raw.get("max_text_chars", 20_000))),
            max_topics_per_note=max(1, min(10, int(raw.get("max_topics_per_note", 4)))),
            remote_name=str(raw.get("remote_name", "origin")).strip() or "origin",
        )
    return repositories


def get_local_note_repositories(cfg: dict | None = None) -> list[LocalNoteRepository]:
    cfg = cfg if cfg is not None else load_merged_config()
    machine_name = resolve_local_machine_name(cfg)
    bindings = (
        ((cfg.get(machine_name, {}) or {}).get("notes", {}) or {})
        .get("repositories", {}) or {}
    )
    definitions = get_note_repositories(cfg)
    out: list[LocalNoteRepository] = []
    for name, raw_path in bindings.items():
        definition = definitions.get(str(name))
        if definition is None:
            continue
        path = raw_path.get("path") if isinstance(raw_path, dict) else raw_path
        if path:
            out.append(LocalNoteRepository(definition, Path(str(path)).expanduser()))
    return out


def is_harqis_host(cfg: dict | None = None) -> bool:
    cfg = cfg if cfg is not None else load_merged_config()
    return resolve_local_machine_name(cfg) == HARQIS_SERVER_MACHINE_NAME
