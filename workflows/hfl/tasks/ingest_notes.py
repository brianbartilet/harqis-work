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
from datetime import date, datetime
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
_DAILY_SCRUM_HEADING_RE = re.compile(
    r"(?im)^\s*(?:#{1,6}\s*)?(?:dsm|daily\s+(?:scrum|stand[- ]?up)(?:\s+meeting)?)\s*:?[ \t]*$"
)
_DAILY_SCRUM_PATH_RE = re.compile(
    r"(?i)(?:^|[/\\ _\-[\(])(?:dsm|daily[- _]?(?:scrum|standup))(?:$|[/\\ _\-\]\)])"
)
_HFL_BLOCK_HEADER_RE = re.compile(
    r"^##\s+(\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?)\s*$"
)
_HFL_BLOCK_FIELD_RE = re.compile(
    r"^###\s+(Moment|What happened|Why it stayed|Possible use|Tags|References)\s*:\s*(.*)$",
    re.IGNORECASE,
)
_HFL_BLOCK_FIELDS = {
    "moment": "moment",
    "what happened": "what_happened",
    "why it stayed": "why_it_stayed",
    "possible use": "possible_use",
    "tags": "tags",
    "references": "references",
}


@dataclass(frozen=True)
class NoteChange:
    status: str
    path: str
    old_path: str = ""
    kind: str = "reference"
    content: str = ""
    changed_at: Optional[datetime] = None
    # New-file or update lines on the right side of the Git diff. An empty
    # tuple means the range is unavailable, so structured-block detection
    # conservatively considers the whole current file.
    changed_lines: tuple[int, ...] = ()


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


def _changed_line_numbers(
    repository: NoteRepository,
    from_commit: str,
    to_commit: str,
    path: str,
) -> tuple[int, ...]:
    """Return right-side line numbers added or updated in one Git diff."""
    result = _git(repository.host_path, [
        "diff", "--unified=0", "--no-color", from_commit, to_commit, "--", path,
    ])
    if result.returncode != 0:
        return ()
    changed: list[int] = []
    for raw in result.stdout.splitlines():
        match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", raw)
        if not match:
            continue
        start = int(match.group(1))
        count = int(match.group(2) or "1")
        if count == 0:
            # A deletion has no right-side lines. Use its insertion point so
            # an edited structured block can still be selected.
            changed.append(max(1, start))
        else:
            changed.extend(range(start, start + count))
    return tuple(changed)


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
        changed_lines = (
            _changed_line_numbers(repository, from_commit, head, rel)
            if status != "D" and kind == "text"
            else ()
        )
        changes.append(NoteChange(
            status=status, path=rel, old_path=old_rel, kind=kind,
            content=content, changed_at=changed_at, changed_lines=changed_lines,
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
    line_count = len(change.content.splitlines())
    return {
        "skip": False,
        "section": Path(change.path).stem,
        "start_line": 1 if line_count else 0,
        "end_line": line_count,
        "is_daily_scrum": bool(
            _DAILY_SCRUM_HEADING_RE.search(change.content)
            or _DAILY_SCRUM_PATH_RE.search(change.path)
        ),
        "moment": f"{action} {Path(change.path).name}",
        "what_happened": excerpt or f"{action} repository artifact `{change.path}`.",
        "why_it_stayed": "",
        "possible_use": "notes reference",
        "core_topic": _slug(Path(change.path).parent.name or Path(change.path).stem),
        "tags": [],
        "synthesized": False,
    }


def _parse_hfl_timestamp(value: str) -> datetime | None:
    normalized = value.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    return None


def _structured_hfl_segments(change: NoteChange) -> list[dict[str, Any]]:
    """Extract changed macro-generated blocks matching the HFL entry shape."""
    if change.kind != "text" or not change.content:
        return []
    lines = change.content.splitlines()
    headers = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := _HFL_BLOCK_HEADER_RE.match(line.strip()))
    ]
    changed = set(change.changed_lines)
    segments: list[dict[str, Any]] = []
    for header_index, (start, header) in enumerate(headers):
        end = headers[header_index + 1][0] if header_index + 1 < len(headers) else len(lines)
        values: dict[str, list[str]] = {}
        current = ""
        block_end = end
        for offset, raw in enumerate(lines[start + 1:end], start + 1):
            field = _HFL_BLOCK_FIELD_RE.match(raw.strip())
            if field:
                current = _HFL_BLOCK_FIELDS[field.group(1).lower()]
                values.setdefault(current, [])
                if field.group(2).strip():
                    values[current].append(field.group(2).strip())
                continue
            stripped = raw.strip()
            if current and re.fullmatch(r"={8,}", stripped):
                block_end = offset + 1
                break
            if current:
                values[current].append(raw.rstrip())
        if not values:
            # A date-like H2 alone is a common daily-note heading, not an HFL
            # macro block. Leave it to the contextual analysis fallback.
            continue
        one_based = set(range(start + 1, block_end + 1))
        if changed and changed.isdisjoint(one_based):
            continue

        def field_text(name: str) -> str:
            return "\n".join(values.get(name, [])).strip()

        tags_text = field_text("tags")
        tags = re.findall(r"#([A-Za-z0-9][A-Za-z0-9_-]*)", tags_text)
        references = [
            line.strip().removeprefix("- ").strip()
            for line in values.get("references", [])
            if line.strip().removeprefix("- ").strip()
        ]
        moment = field_text("moment")
        what_happened = field_text("what_happened")
        possible_use = field_text("possible_use")
        meaningful = any((moment, what_happened, possible_use, tags, references))
        core_candidates = [
            tag for tag in tags if tag.lower() not in {"notes", "daily"}
        ]
        segments.append({
            "skip": not meaningful,
            "structured_hfl": True,
            "section": f"HFL block {header.group(1)}",
            "start_line": start + 1,
            "end_line": block_end,
            "when": _parse_hfl_timestamp(header.group(1)),
            "is_daily_scrum": bool(
                _DAILY_SCRUM_HEADING_RE.search(change.content)
                or _DAILY_SCRUM_PATH_RE.search(change.path)
            ),
            "moment": moment,
            "what_happened": what_happened,
            "why_it_stayed": field_text("why_it_stayed"),
            "possible_use": possible_use,
            "core_topic": _slug(
                core_candidates[0] if core_candidates else moment,
                fallback=_slug(Path(change.path).stem),
            ),
            "tags": tags,
            "references": references,
            "synthesized": False,
        })
    return segments


def _normalize_segment(
    raw: dict[str, Any],
    fallback: dict[str, Any],
    *,
    max_line: int,
) -> dict[str, Any]:
    segment = dict(fallback)
    for key in (
        "section", "moment", "what_happened", "why_it_stayed",
        "possible_use", "core_topic",
    ):
        if key in raw:
            segment[key] = str(raw.get(key, "")).strip()
    segment["skip"] = bool(raw.get("skip", False))
    if isinstance(raw.get("is_daily_scrum"), bool):
        segment["is_daily_scrum"] = raw["is_daily_scrum"]
    segment["tags"] = [
        str(tag).strip().lstrip("#") for tag in (raw.get("tags") or [])
        if str(tag).strip()
    ]
    if fallback.get("structured_hfl"):
        # Macro fields are authored source data. The model may fill blanks and
        # enrich tags, but it must not rewrite populated fields.
        for key in (
            "section", "moment", "what_happened", "why_it_stayed",
            "possible_use", "core_topic", "when", "references",
            "start_line", "end_line",
        ):
            if fallback.get(key):
                segment[key] = fallback[key]
        segment["structured_hfl"] = True
        segment["skip"] = bool(fallback.get("skip", False))
        segment["tags"] = list(dict.fromkeys([
            *fallback.get("tags", []), *segment["tags"],
        ]))
    try:
        start = int(raw.get("start_line", 0))
        end = int(raw.get("end_line", 0))
    except (TypeError, ValueError):
        start = end = 0
    if max_line and start > 0 and end >= start:
        segment["start_line"] = min(start, max_line)
        segment["end_line"] = min(max(end, segment["start_line"]), max_line)
    else:
        segment["start_line"] = segment["end_line"] = 0
    if fallback.get("structured_hfl"):
        segment["start_line"] = fallback["start_line"]
        segment["end_line"] = fallback["end_line"]
    segment["synthesized"] = True
    return segment


def _segments_from_parsed(
    parsed: dict[str, Any] | None,
    fallback: dict[str, Any],
    *,
    max_segments: int,
    max_line: int,
) -> list[dict[str, Any]]:
    if not parsed:
        return [fallback]
    raw_segments = parsed.get("segments")
    if not isinstance(raw_segments, list):
        raw_segments = [parsed]  # tolerate the pre-segmentation response shape
    segments = [
        _normalize_segment(raw, fallback, max_line=max_line)
        for raw in raw_segments[:max_segments]
        if isinstance(raw, dict)
    ]
    return segments or [fallback]


def _structured_segments_from_parsed(
    parsed: dict[str, Any] | None,
    fallbacks: list[dict[str, Any]],
    *,
    max_line: int,
) -> list[dict[str, Any]]:
    raw_segments = parsed.get("segments") if parsed else None
    if not isinstance(raw_segments, list):
        raw_segments = []
    return [
        _normalize_segment(
            raw_segments[index] if index < len(raw_segments) and isinstance(raw_segments[index], dict) else {},
            fallback,
            max_line=max_line,
        )
        for index, fallback in enumerate(fallbacks)
    ]


def distill_note_segments(
    repository: NoteRepository,
    change: NoteChange,
    *,
    synthesize: bool = True,
    model: str = _DEFAULT_HAIKU,
    cfg_id: str = "ANTHROPIC",
    max_segments: int | None = None,
    max_tokens: int | None = None,
) -> list[dict[str, Any]]:
    """Distill one change into bounded, naturally transitioned topic segments."""
    fallback = _fallback_distillation(change)
    structured = _structured_hfl_segments(change)
    if structured:
        structured = structured[:max(
            1, min(10, max_segments or repository.max_topics_per_note)
        )]
    if not synthesize:
        return structured or [fallback]
    segment_cap = 1 if change.kind != "text" else max(
        1, min(10, max_segments or repository.max_topics_per_note)
    )
    token_cap = max_tokens or min(3200, 700 + segment_cap * 450)
    instruction = (
        f"Repository: {repository.name}\nStatus: {change.status}\n"
        f"Path: {change.path}\nOld path: {change.old_path or '(none)'}\n"
        f"Maximum topic segments: {segment_cap}\n"
    )
    if structured:
        instruction += (
            f"Detected structured HFL macro blocks: {len(structured)}\n"
            "Return exactly one segment per detected block, in source order. "
            "Preserve populated HFL fields and source tags; infer retention "
            "context when useful and add relevant tags grounded in the block.\n"
        )
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            return [fallback]
        if change.kind == "image":
            from workflows.hfl.tasks.analyze_media import _encode_image
            local = _safe_checkout_path(repository, change.path)
            image = _encode_image(local) if local and local.is_file() else None
            if image is None:
                return [fallback]
            response = client.send_messages(
                messages=[{"role": "user", "content": [
                    image,
                    {"type": "text", "text": instruction + "Analyze this changed image and return JSON only."},
                ]}],
                model=model, max_tokens=token_cap,
                system=load_prompt("ingest_notes").strip(),
            )
        else:
            selected_lines = set()
            for segment in structured:
                selected_lines.update(range(
                    int(segment["start_line"]), int(segment["end_line"]) + 1,
                ))
            numbered = "\n".join(
                f"{line_no}: {line}"
                for line_no, line in enumerate(change.content.splitlines(), 1)
                if not structured or line_no in selected_lines
            )
            response = client.send_message(
                prompt=instruction + "\nLine-numbered note content:\n" + numbered,
                system=load_prompt("ingest_notes").strip(),
                model=model, max_tokens=token_cap,
            )
        text = response.content[0].text if response and response.content else ""
        parsed = _parse_model_json(text)
        if structured:
            return _structured_segments_from_parsed(
                parsed, structured, max_line=len(change.content.splitlines()),
            )
        return _segments_from_parsed(
            parsed, fallback, max_segments=segment_cap,
            max_line=len(change.content.splitlines()),
        )
    except Exception as exc:  # noqa: BLE001 - one note must not break Beat
        _log.warning("notes distillation failed for %s (%s) — fallback", change.path, exc)
        return structured or [fallback]


def distill_note_change(
    repository: NoteRepository,
    change: NoteChange,
    **kwargs,
) -> dict[str, Any]:
    """Compatibility wrapper returning the first distilled topic segment."""
    kwargs.pop("max_segments", None)
    return distill_note_segments(repository, change, max_segments=1, **kwargs)[0]


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
                "Maximum topic segments: 1\n"
                f"Changed artifacts ({len(changes)}):\n" + "\n".join(lines)
            ),
            system=load_prompt("ingest_notes").strip(), model=model,
            max_tokens=max_tokens,
        )
        parsed = _parse_model_json(response.content[0].text if response and response.content else "")
        return _segments_from_parsed(
            parsed, fallback, max_segments=1, max_line=0,
        )[0]
    except Exception as exc:  # noqa: BLE001
        _log.warning("notes summary distillation failed (%s) — fallback", exc)
        return fallback


def _entry_tags(repository: NoteRepository, distilled: dict[str, Any]) -> list[str]:
    is_daily_scrum = distilled.get("is_daily_scrum") is True
    ordered = ["notes", f"repo-{_slug(repository.name)}"]
    if is_daily_scrum:
        ordered.append("dsm")
    ordered.append(_slug(str(distilled.get("core_topic", ""))))
    if distilled.get("structured_hfl"):
        ordered.extend(str(tag) for tag in distilled.get("tags") or [])
        ordered.extend(repository.tags)
    else:
        ordered.extend(repository.tags)
        ordered.extend(str(tag) for tag in distilled.get("tags") or [])
    out: list[str] = []
    for tag in ordered:
        normalized = _slug(str(tag))
        if normalized == "dsm" and not is_daily_scrum:
            continue
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
    section = str(distilled.get("section", "")).strip()
    start_line = int(distilled.get("start_line", 0) or 0)
    end_line = int(distilled.get("end_line", 0) or 0)
    section_context = ""
    if section:
        line_context = f" (lines {start_line}-{end_line})" if start_line and end_line else ""
        section_context = f"Section: {section}{line_context}.\n\n"
    entry = _build_entry(
        when=when,
        moment=str(distilled.get("moment", "")),
        what_happened=section_context + str(distilled.get("what_happened", "")),
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


def _segment_references(
    repository: NoteRepository,
    head: str,
    change: NoteChange,
    segment: dict[str, Any],
) -> list[str]:
    blob = _blob_url(repository, head, change.path)
    start = int(segment.get("start_line", 0) or 0)
    end = int(segment.get("end_line", 0) or 0)
    if start and end:
        blob += f"#L{start}-L{end}"
    references = [blob]
    local = _safe_checkout_path(repository, change.path)
    if local:
        references.append(str(local))
    references.extend(str(item) for item in segment.get("references") or [])
    return list(dict.fromkeys(item for item in references if item))


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

            eligible: list[NoteChange] = []
            summary: list[NoteChange] = []
            media_count = 0
            for change in changes:
                can_distill = change.status != "D" and change.kind in {"text", "image"}
                if change.kind == "image" and media_count >= repository.max_media:
                    can_distill = False
                if can_distill:
                    eligible.append(change)
                    if change.kind == "image":
                        media_count += 1
                else:
                    summary.append(change)

            granular: list[tuple[NoteChange, dict[str, Any]]] = []
            skipped = topic_overflow = 0
            for index, change in enumerate(eligible):
                if len(granular) >= repository.max_entries:
                    summary.extend(eligible[index:])
                    break
                segments = distill_note_segments(
                    repository, change, synthesize=synthesize,
                    model=model, cfg_id=cfg_id__anthropic,
                    max_segments=repository.max_topics_per_note,
                )
                skipped += sum(bool(segment.get("skip")) for segment in segments)
                segments = [segment for segment in segments if not segment.get("skip")]
                available = repository.max_entries - len(granular)
                granular.extend((change, segment) for segment in segments[:available])
                if len(segments) > available:
                    summary.append(change)
                    topic_overflow += len(segments) - available

            # The total cap includes the overflow/reference summary. If topic
            # entries consumed every slot, move the final one into that summary.
            if summary and len(granular) >= repository.max_entries:
                overflow_change, _ = granular.pop()
                summary.append(overflow_change)
                topic_overflow += 1

            # Summaries list files, not repeated omitted topic segments.
            summary = list({(change.status, change.path): change for change in summary}.values())

            written = indexed = 0
            for change, distilled in granular:
                entry_when = distilled.get("when")
                if not isinstance(entry_when, datetime):
                    entry_when = change.changed_at or datetime.now()
                did_write, did_index = _write_entry(
                    repository, distilled,
                    when=entry_when,
                    references=_segment_references(repository, head, change, distilled),
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
                "topic_entries": len(granular), "topic_overflow": topic_overflow,
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
