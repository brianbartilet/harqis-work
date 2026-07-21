"""Repository-backed notes → granular HFL Activity Corpus entries.

The canonical HARQIS host reads configured clean checkouts after the notes
workflow records a successful clone/pull. The first run stores ``HEAD`` as the
baseline. Later runs diff the stored commit against ``HEAD``, distill each
bounded text note or common image with Haiku, create a summary for overflow and
reference-only artifacts, then submit every entry through the canonical HFL
Markdown + Elasticsearch persistence boundary.

Git authentication is inherited from the host. Missing configuration, stale or
failed pulls, an empty diff, and first activation are clean no-ops. The cursor
advances only after every accepted entry has been durably submitted.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
from workflows.hfl.prompts import load_prompt
from workflows.hfl.tasks.capture import _build_entry, append_entry, resolve_corpus_dir
from workflows.hfl.tasks.ingest_git import _parse_model_json
from workflows.notes.config import NoteRepository, get_note_repositories
from workflows.notes.state import (
    load_ingest_cursor,
    recent_pull_succeeded,
    store_ingest_cursor,
)

_log = create_logger("hfl.ingest_notes")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"
_TEXT_EXTS = {".md", ".markdown", ".txt", ".rst", ".org"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


@dataclass(frozen=True)
class NoteChange:
    status: str
    path: str
    old_path: str = ""
    kind: str = "reference"
    content: str = ""
    changed_at: Optional[datetime] = None


def _git(path: Path, args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(path), timeout=timeout,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def _head(repository: NoteRepository) -> str:
    result = _git(repository.host_path, ["rev-parse", "HEAD"])
    return result.stdout.strip() if result.returncode == 0 else ""


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
        if pattern.startswith("**/") and fnmatch.fnmatch(path, pattern[3:]):
            return True
    return False


def _included(repository: NoteRepository, path: str) -> bool:
    if repository.exclude_globs and _matches(path, repository.exclude_globs):
        return False
    return not repository.include_globs or _matches(path, repository.include_globs)


def _kind(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in _TEXT_EXTS:
        return "text"
    if suffix in _IMAGE_EXTS:
        return "image"
    return "reference"


def _safe_checkout_path(repository: NoteRepository, relative: str) -> Path | None:
    root = repository.host_path.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _changed_at(repository: NoteRepository, commit: str, path: str) -> datetime | None:
    result = _git(repository.host_path, [
        "log", "-1", "--format=%cI", commit, "--", path,
    ])
    try:
        return datetime.fromisoformat(result.stdout.strip().replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _parse_name_status(text: str) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for raw in text.splitlines():
        parts = raw.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        if status.startswith("R") and len(parts) >= 3:
            out.append(("R", parts[2], parts[1]))
        else:
            out.append((status[:1], parts[1], ""))
    return out


def collect_note_changes(
    repository: NoteRepository,
    *,
    from_commit: str,
    to_commit: str = "HEAD",
    since: date | None = None,
    until: date | None = None,
) -> dict[str, Any]:
    """Collect bounded metadata/content for files changed in a Git range."""
    ancestor = _git(repository.host_path, ["merge-base", "--is-ancestor", from_commit, to_commit])
    if ancestor.returncode != 0:
        raise ValueError("stored cursor is not an ancestor of the current head")
    head_result = _git(repository.host_path, ["rev-parse", to_commit])
    head = head_result.stdout.strip()
    diff = _git(repository.host_path, [
        "diff", "--name-status", "-M", f"{from_commit}..{head}", "--",
    ])
    if diff.returncode != 0:
        raise RuntimeError((diff.stderr or diff.stdout or "git diff failed").strip()[:300])

    changes: list[NoteChange] = []
    for status, rel, old_rel in _parse_name_status(diff.stdout):
        if not _included(repository, rel):
            continue
        changed_at = _changed_at(repository, head, rel)
        if since and changed_at and changed_at.date() < since:
            continue
        if until and changed_at and changed_at.date() > until:
            continue
        kind = _kind(rel)
        content = ""
        if status != "D" and kind == "text":
            local = _safe_checkout_path(repository, rel)
            if local and local.is_file():
                content = local.read_text(encoding="utf-8", errors="replace")[:repository.max_text_chars]
        changes.append(NoteChange(
            status=status, path=rel, old_path=old_rel, kind=kind,
            content=content, changed_at=changed_at,
        ))
    return {
        "repository": repository.name,
        "from_commit": from_commit,
        "head": head,
        "changes": changes,
        "change_count": len(changes),
    }


def _slug(value: str, fallback: str = "notes") -> str:
    result = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return result[:48] or fallback


def _github_base(remote: str) -> str:
    value = remote.strip()
    if value.startswith("git@github.com:"):
        value = "https://github.com/" + value.split(":", 1)[1]
    elif value.startswith("ssh://git@github.com/"):
        value = "https://github.com/" + value.split("github.com/", 1)[1]
    return value[:-4] if value.endswith(".git") else value.rstrip("/")


def _blob_url(repository: NoteRepository, commit: str, path: str) -> str:
    return f"{_github_base(repository.remote)}/blob/{commit}/{quote(path, safe='/')}"


def _compare_url(repository: NoteRepository, old: str, new: str) -> str:
    return f"{_github_base(repository.remote)}/compare/{old}...{new}"


def _fallback_distillation(change: NoteChange) -> dict[str, Any]:
    action = {"A": "Added", "M": "Updated", "R": "Renamed", "D": "Deleted"}.get(change.status, "Changed")
    excerpt = " ".join(change.content.split())[:800]
    return {
        "skip": False,
        "moment": f"{action} {Path(change.path).name}",
        "what_happened": excerpt or f"{action} repository artifact `{change.path}`.",
        "why_it_stayed": "",
        "possible_use": "notes reference",
        "core_topic": _slug(Path(change.path).parent.name or Path(change.path).stem),
        "tags": [],
        "synthesized": False,
    }


def distill_note_change(
    repository: NoteRepository,
    change: NoteChange,
    *,
    synthesize: bool = True,
    model: str = _DEFAULT_HAIKU,
    cfg_id: str = "ANTHROPIC",
    max_tokens: int = 900,
) -> dict[str, Any]:
    """Distill one text/image change with a raw metadata fallback."""
    fallback = _fallback_distillation(change)
    if not synthesize:
        return fallback
    instruction = (
        f"Repository: {repository.name}\nStatus: {change.status}\n"
        f"Path: {change.path}\nOld path: {change.old_path or '(none)'}\n"
    )
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            return fallback
        if change.kind == "image":
            from workflows.hfl.tasks.analyze_media import _encode_image
            local = _safe_checkout_path(repository, change.path)
            image = _encode_image(local) if local and local.is_file() else None
            if image is None:
                return fallback
            response = client.send_messages(
                messages=[{"role": "user", "content": [
                    image,
                    {"type": "text", "text": instruction + "Analyze this changed image and return JSON only."},
                ]}],
                model=model, max_tokens=max_tokens,
                system=load_prompt("ingest_notes").strip(),
            )
        else:
            response = client.send_message(
                prompt=instruction + "\nNote content:\n" + change.content,
                system=load_prompt("ingest_notes").strip(),
                model=model, max_tokens=max_tokens,
            )
        text = response.content[0].text if response and response.content else ""
        parsed = _parse_model_json(text)
        if not parsed:
            return fallback
        for key in ("moment", "what_happened", "why_it_stayed", "possible_use", "core_topic"):
            parsed[key] = str(parsed.get(key, "")).strip()
        parsed["tags"] = [str(tag).strip().lstrip("#") for tag in (parsed.get("tags") or [])]
        parsed.setdefault("skip", False)
        parsed["synthesized"] = True
        return parsed
    except Exception as exc:  # noqa: BLE001 - one note must not break Beat
        _log.warning("notes distillation failed for %s (%s) — fallback", change.path, exc)
        return fallback


def distill_change_summary(
    repository: NoteRepository,
    changes: list[NoteChange],
    *,
    synthesize: bool = True,
    model: str = _DEFAULT_HAIKU,
    cfg_id: str = "ANTHROPIC",
    max_tokens: int = 900,
) -> dict[str, Any]:
    lines = []
    for change in changes[:200]:
        excerpt = " ".join(change.content.split())[:300] if change.content else ""
        lines.append(f"- {change.status} {change.path}" + (f": {excerpt}" if excerpt else ""))
    fallback = {
        "skip": False,
        "moment": f"Captured {len(changes)} additional note repository change(s)",
        "what_happened": "\n".join(lines),
        "why_it_stayed": "The grouped record preserves changes beyond the granular daily cap.",
        "possible_use": "notes archive",
        "core_topic": "notes-sync",
        "tags": [],
        "synthesized": False,
    }
    if not synthesize:
        return fallback
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            return fallback
        response = client.send_message(
            prompt=(
                f"Repository: {repository.name}\nMode: bounded multi-file summary\n"
                f"Changed artifacts ({len(changes)}):\n" + "\n".join(lines)
            ),
            system=load_prompt("ingest_notes").strip(), model=model,
            max_tokens=max_tokens,
        )
        parsed = _parse_model_json(response.content[0].text if response and response.content else "")
        if not parsed:
            return fallback
        for key in ("moment", "what_happened", "why_it_stayed", "possible_use", "core_topic"):
            parsed[key] = str(parsed.get(key, "")).strip()
        parsed["tags"] = [str(tag).strip().lstrip("#") for tag in (parsed.get("tags") or [])]
        parsed.setdefault("skip", False)
        parsed["synthesized"] = True
        return parsed
    except Exception as exc:  # noqa: BLE001
        _log.warning("notes summary distillation failed (%s) — fallback", exc)
        return fallback


def _entry_tags(repository: NoteRepository, distilled: dict[str, Any]) -> list[str]:
    ordered = ["notes", "dsm", f"repo-{_slug(repository.name)}"]
    ordered.extend(repository.tags)
    ordered.append(_slug(str(distilled.get("core_topic", ""))))
    ordered.extend(str(tag) for tag in distilled.get("tags") or [])
    out: list[str] = []
    for tag in ordered:
        normalized = _slug(str(tag))
        if normalized and normalized not in out:
            out.append(normalized)
    return out[:6]


def _write_entry(
    repository: NoteRepository,
    distilled: dict[str, Any],
    *,
    when: datetime,
    references: list[str],
) -> tuple[bool, bool]:
    if distilled.get("skip"):
        return False, False
    entry = _build_entry(
        when=when,
        moment=str(distilled.get("moment", "")),
        what_happened=str(distilled.get("what_happened", "")),
        why_it_stayed=str(distilled.get("why_it_stayed", "")),
        possible_use=str(distilled.get("possible_use", "")) or "notes reference",
        tags=_entry_tags(repository, distilled), references=references,
    )
    day_file = resolve_corpus_dir() / f"{when.strftime('%Y-%m-%d')}.md"
    _, doc_id = append_entry(
        day_file, entry, source="notes",
        synthesized=bool(distilled.get("synthesized")),
    )
    return True, doc_id is not None


def collect_notes_activity(
    repository_name: str,
    *,
    from_commit: str | None = None,
    to_commit: str = "HEAD",
    since: date | None = None,
    until: date | None = None,
) -> dict[str, Any]:
    repositories = get_note_repositories()
    repository = repositories.get(repository_name)
    if repository is None:
        raise KeyError(f"unknown notes repository: {repository_name}")
    cursor = from_commit or load_ingest_cursor(repository_name)
    head = _head(repository)
    if not cursor:
        return {"repository": repository_name, "head": head, "baseline_required": True,
                "changes": [], "change_count": 0}
    return collect_note_changes(
        repository, from_commit=cursor, to_commit=to_commit,
        since=since, until=until,
    )


@SPROUT.task()
@log_result()
def ingest_notes_activity(
    *,
    repository_names: Optional[list[str]] = None,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    synthesize: bool = True,
    pull_max_age_minutes: int = 90,
) -> dict[str, Any]:
    """Ingest changed note files after a successful host pull."""
    repositories = get_note_repositories()
    selected = repository_names or sorted(repositories)
    if not selected:
        return {"skipped": "no note repositories configured", "entries_written": 0}

    results: dict[str, dict[str, Any]] = {}
    total_entries = total_indexed = 0
    for name in selected:
        repository = repositories.get(name)
        if repository is None:
            results[name] = {"skipped": "unknown repository", "entries_written": 0}
            continue
        head = _head(repository)
        if not head or not recent_pull_succeeded(
            name, head=head, max_age_minutes=pull_max_age_minutes,
        ):
            results[name] = {"skipped": "no recent successful host pull", "entries_written": 0}
            continue
        cursor = load_ingest_cursor(name)
        if not cursor:
            store_ingest_cursor(name, head)
            results[name] = {"skipped": "baseline initialized", "baseline": head, "entries_written": 0}
            continue
        if cursor == head:
            results[name] = {"skipped": "no changes", "head": head, "entries_written": 0}
            continue

        try:
            activity = collect_note_changes(repository, from_commit=cursor, to_commit=head)
            changes: list[NoteChange] = activity["changes"]
            if not changes:
                store_ingest_cursor(name, head)
                results[name] = {"skipped": "no qualifying changes", "head": head, "entries_written": 0}
                continue

            granular: list[NoteChange] = []
            summary: list[NoteChange] = []
            media_count = 0
            for change in changes:
                eligible = change.status != "D" and change.kind in {"text", "image"}
                if change.kind == "image" and media_count >= repository.max_media:
                    eligible = False
                if eligible and len(granular) < repository.max_entries:
                    granular.append(change)
                    if change.kind == "image":
                        media_count += 1
                else:
                    summary.append(change)

            written = indexed = skipped = 0
            for change in granular:
                distilled = distill_note_change(
                    repository, change, synthesize=synthesize,
                    model=model, cfg_id=cfg_id__anthropic,
                )
                local = _safe_checkout_path(repository, change.path)
                references = [_blob_url(repository, head, change.path)]
                if local:
                    references.append(str(local))
                did_write, did_index = _write_entry(
                    repository, distilled,
                    when=change.changed_at or datetime.now(), references=references,
                )
                written += int(did_write)
                indexed += int(did_index)
                skipped += int(not did_write)

            if summary:
                distilled = distill_change_summary(
                    repository, summary, synthesize=synthesize,
                    model=model, cfg_id=cfg_id__anthropic,
                )
                did_write, did_index = _write_entry(
                    repository, distilled, when=datetime.now(),
                    references=[
                        _compare_url(repository, cursor, head),
                        str(repository.host_path.resolve()),
                    ],
                )
                written += int(did_write)
                indexed += int(did_index)
                skipped += int(not did_write)

            store_ingest_cursor(name, head)
            total_entries += written
            total_indexed += indexed
            results[name] = {
                "entries_written": written, "indexed": indexed,
                "files_changed": len(changes), "granular": len(granular),
                "summarized": len(summary), "distilled_skips": skipped,
                "from_commit": cursor, "head": head,
            }
        except Exception as exc:  # noqa: BLE001 - cursor must remain retryable
            _log.error("notes ingest failed for %s (%s)", name, exc)
            results[name] = {"error": str(exc)[:300], "entries_written": 0, "cursor_advanced": False}

    return {
        "entries_written": total_entries,
        "indexed": total_indexed,
        "repositories": results,
        "model": model if synthesize and total_entries else None,
    }
