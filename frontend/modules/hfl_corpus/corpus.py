"""Recursive HFL corpus index, metadata extraction, and search."""

from __future__ import annotations

import html
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from threading import Lock, Thread
from typing import TYPE_CHECKING

from config import get_settings
from web import REPO_ROOT

if TYPE_CHECKING:
    from services.safe_paths import ReferenceLink


_HEADER = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_DATE_IN_NAME = re.compile(r"(20\d{2}-\d{2}-\d{2})")
_TAG_LINE = re.compile(r"^\s*Tags:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_TAG_TOKEN = re.compile(r"(?<!\w)#([\w-]+)", re.UNICODE)
_NON_SLUG = re.compile(r"[^a-z0-9]+")
_GIT_SHA = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)
_MONTH_DIRECTORY_ORDER = {
    name.casefold(): index
    for index, name in enumerate(
        (
            "Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
        ),
        start=1,
    )
}
_HFL_FIELD = re.compile(
    r"^\s*(Source|Machine|Entry ID|Moment|What happened|Why it stayed|Possible use|Tags|References):\s*(.*?)\s*$",
    re.IGNORECASE,
)
_HFL_FIELD_LABELS = {
    "moment": "Moment",
    "what happened": "What happened",
    "why it stayed": "Why it stayed",
    "possible use": "Possible use",
    "tags": "Tags",
    "references": "References",
    "source": "Source",
    "machine": "Machine",
    "entry id": "Entry ID",
}
PAGE_SIZES = (20, 50, 100)


@dataclass(frozen=True)
class CorpusEntry:
    anchor: str
    header: str
    moment: str
    what_happened: str
    tags: tuple[str, ...]
    source: str = ""
    text: str = ""
    secret: bool = False


@dataclass(frozen=True)
class CorpusDocument:
    relative_path: str
    path: Path | None
    name: str
    text: str
    created_at: datetime
    updated_at: datetime
    tags: tuple[str, ...]
    references: tuple[str, ...]
    excerpt: str
    tag_counts: tuple[tuple[str, int], ...] = ()
    entry_count: int = 0
    entries: tuple[CorpusEntry, ...] = ()
    matching_entry_count: int | None = None
    tag_entry_anchors: tuple[tuple[str, str], ...] = ()

    def matching_entries(
        self,
        selected_tags: str | tuple[str, ...],
        phrase: str = "",
        source: str = "",
    ) -> tuple[CorpusEntry, ...]:
        needles = _tag_needles(selected_tags)
        text_needle = (phrase or "").strip().casefold()
        source_needle = (source or "").strip().casefold()
        if not needles and not text_needle and not source_needle:
            return ()
        return tuple(
            entry
            for entry in self.entries
            if all(
                any(needle in tag.casefold() for tag in entry.tags)
                for needle in needles
            )
            and (not text_needle or text_needle in entry.text.casefold())
            and (
                not source_needle
                or entry.source.strip().casefold() == source_needle
            )
        )

    def first_matching_entry_anchor(self, tag: str) -> str:
        normalized = tag.strip().lstrip("#").casefold()
        for entry_tag, anchor in self.tag_entry_anchors:
            if entry_tag.casefold() == normalized:
                return anchor
        matches = self.matching_entries(normalized)
        return matches[0].anchor if matches else ""

    def matching_text_entries(self, phrase: str) -> tuple[CorpusEntry, ...]:
        needle = (phrase or "").strip().casefold()
        if not needle:
            return ()
        return tuple(entry for entry in self.entries if needle in entry.text.casefold())

    def ordered_tag_counts(
        self, selected_tags: str | tuple[str, ...]
    ) -> tuple[tuple[str, int], ...]:
        needles = _tag_needles(selected_tags)
        if not needles:
            return self.tag_counts

        counts = dict(self.tag_counts)
        for tag in self.tags:
            if not self.tag_matches(tag, needles) or tag in counts:
                continue
            counts[tag] = sum(
                1
                for entry in self.entries
                if any(tag.casefold() == entry_tag.casefold() for entry_tag in entry.tags)
            )

        return tuple(
            sorted(
                counts.items(),
                key=lambda item: (
                    not self.tag_matches(item[0], needles),
                    item[0].casefold() not in needles,
                ),
            )
        )

    @staticmethod
    def tag_matches(tag: str, selected_tags: str | tuple[str, ...]) -> bool:
        needles = _tag_needles(selected_tags)
        folded_tag = tag.casefold()
        return any(needle in folded_tag for needle in needles)


@dataclass(frozen=True)
class CorpusPage:
    items: tuple[CorpusDocument, ...]
    page: int
    page_size: int
    total_results: int
    total_pages: int
    start: int
    end: int

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages


def paginate_documents(
    documents: list[CorpusDocument] | tuple[CorpusDocument, ...],
    *,
    page: int = 1,
    page_size: int = 20,
) -> CorpusPage:
    normalized_size = page_size if page_size in PAGE_SIZES else PAGE_SIZES[0]
    total_results = len(documents)
    total_pages = max(1, (total_results + normalized_size - 1) // normalized_size)
    normalized_page = min(max(1, page), total_pages)
    offset = (normalized_page - 1) * normalized_size
    items = tuple(documents[offset: offset + normalized_size])
    return CorpusPage(
        items=items,
        page=normalized_page,
        page_size=normalized_size,
        total_results=total_results,
        total_pages=total_pages,
        start=offset + 1 if items else 0,
        end=offset + len(items),
    )


def _tag_needles(selected_tags: str | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(selected_tags, str):
        selected_tags = (selected_tags,)
    return tuple(tag.casefold() for tag in selected_tags if tag)


def resolve_corpus_root() -> Path:
    try:
        from apps.apps_config import CONFIG_MANAGER

        hfl = CONFIG_MANAGER.get("HFL")
        configured = (hfl.get("corpus") or {}).get("path") if isinstance(hfl, dict) else None
        if configured and "${" not in configured:
            return Path(configured).expanduser().resolve()
    except Exception:
        pass
    configured = get_settings().hfl_corpus_path.strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (REPO_ROOT / "logs" / "hfl").resolve()


def _entry_blocks(text: str) -> list[tuple[str, str]]:
    matches = list(_HEADER.finditer(text))
    return [
        (match.group(1).strip(), text[match.end(): matches[index + 1].start() if index + 1 < len(matches) else len(text)].strip())
        for index, match in enumerate(matches)
    ]


def _entry_anchor(header: str, index: int) -> str:
    slug = _NON_SLUG.sub("-", header.casefold()).strip("-")[:48] or "entry"
    return f"hfl-entry-{index + 1}-{slug}"


def _field_blocks(body: str) -> dict[str, str]:
    fields: dict[str, list[str]] = {}
    current = ""
    for raw in body.splitlines():
        field = _HFL_FIELD.match(raw)
        if field:
            current = field.group(1).casefold()
            fields[current] = [field.group(2).strip()]
        elif current:
            fields[current].append(raw.rstrip())
    return {
        name: "\n".join(lines).strip()
        for name, lines in fields.items()
    }


def _entry_preview(value: str) -> str:
    lines = [line.strip() for line in (value or "").splitlines()]
    outcome = next(
        (
            index
            for index, line in enumerate(lines)
            if line.casefold() in {"### outcome", "outcome:"}
        ),
        None,
    )
    candidates = lines[outcome + 1:] if outcome is not None else lines
    for line in candidates:
        if not line or line.startswith("#"):
            continue
        return re.sub(r"^(?:[-*•]|\d+[.)])\s+", "", line).strip()
    return ""


def parse_entries(text: str) -> tuple[CorpusEntry, ...]:
    entries: list[CorpusEntry] = []
    for index, (header, body) in enumerate(_entry_blocks(text)):
        fields = _field_blocks(body)
        tags = tuple(
            sorted(
                {
                    token.casefold()
                    for tag_line in _TAG_LINE.findall(body)
                    for token in _TAG_TOKEN.findall(tag_line)
                }
            )
        )
        what_happened = _entry_preview(fields.get("what happened", ""))
        moment = _entry_preview(fields.get("moment", "")) or what_happened or header
        entries.append(
            CorpusEntry(
                anchor=_entry_anchor(header, index),
                header=header,
                moment=moment,
                what_happened=what_happened or moment,
                tags=tags,
                source=fields.get("source", "").strip(),
                text=f"{header}\n{body}",
            )
        )
    return tuple(entries)


def _first_tag_entry_anchors(
    entries: tuple[CorpusEntry, ...],
) -> tuple[tuple[str, str], ...]:
    anchors: dict[str, str] = {}
    for entry in entries:
        for tag in entry.tags:
            anchors.setdefault(tag.casefold(), entry.anchor)
    return tuple(anchors.items())


def _entry_count(text: str) -> int:
    """Count HFL entries from level-two Markdown headers."""
    return sum(1 for _ in _HEADER.finditer(text))


def _entry_metadata(header: str, body: str) -> tuple[datetime | None, tuple[str, ...]]:
    """Read only the timestamp and references needed by the frontend index.

    Keeping this narrow parser local avoids importing ``workflows.hfl`` whose
    package initialiser registers every Celery task as a side effect.
    """
    when = None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            when = datetime.strptime(header.strip(), fmt)
            break
        except ValueError:
            continue

    references: list[str] = []
    collecting_references = False
    for raw in body.splitlines():
        stripped = raw.strip()
        if collecting_references:
            if stripped.startswith("- "):
                reference = stripped[2:].strip()
                if reference and not _GIT_SHA.fullmatch(reference):
                    references.append(reference)
                continue
            if not stripped:
                continue
            collecting_references = False
        if stripped.lower().startswith("references:"):
            collecting_references = True
    return when, tuple(references)


def _metadata(
    path: Path, text: str
) -> tuple[
    datetime,
    tuple[str, ...],
    tuple[str, ...],
    tuple[tuple[str, int], ...],
    int,
]:
    timestamps: list[datetime] = []
    tag_counts: Counter[str] = Counter()
    references: list[str] = []
    entries = _entry_blocks(text)
    for header, body in entries:
        when, entry_references = _entry_metadata(header, body)
        if when:
            timestamps.append(when)
        references.extend(entry_references)
    for tag_line in _TAG_LINE.findall(text):
        tag_counts.update(set(token.lower() for token in _TAG_TOKEN.findall(tag_line)))

    if not timestamps:
        match = _DATE_IN_NAME.search(path.name)
        if match:
            try:
                timestamps.append(datetime.strptime(match.group(1), "%Y-%m-%d"))
            except ValueError:
                pass
    stat = path.stat()
    created = min(timestamps) if timestamps else datetime.fromtimestamp(
        getattr(stat, "st_birthtime", stat.st_ctime)
    )
    ranked_tags = tuple(
        sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))[:10]
    )
    return (
        created,
        tuple(sorted(tag_counts)),
        tuple(dict.fromkeys(references)),
        ranked_tags,
        _entry_count(text),
    )


def _excerpt(text: str, limit: int = 240) -> str:
    compact = " ".join(line.strip() for line in text.splitlines() if line.strip())
    return compact[:limit] + ("…" if len(compact) > limit else "")


class CorpusIndex:
    def __init__(
        self,
        ttl_seconds: int = 30,
        *,
        stale_while_revalidate: bool = False,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.stale_while_revalidate = stale_while_revalidate
        self._loaded_at = 0.0
        self._root: Path | None = None
        self._documents: tuple[CorpusDocument, ...] = ()
        self._file_cache: dict[str, tuple[int, int, CorpusDocument]] = {}
        self._lock = Lock()
        self._refresh_lock = Lock()
        self._refreshing = False

    def documents(self, force: bool = False) -> tuple[CorpusDocument, ...]:
        root = resolve_corpus_root()
        if not force and root == self._root and time.monotonic() - self._loaded_at < self.ttl_seconds:
            return self._documents
        if (
            not force
            and self.stale_while_revalidate
            and root == self._root
            and self._loaded_at
        ):
            self._refresh_in_background()
            return self._documents
        return self._refresh(root, force=force)

    def _refresh_in_background(self) -> None:
        with self._refresh_lock:
            if self._refreshing:
                return
            self._refreshing = True
        Thread(
            target=self._background_refresh,
            name="hfl-corpus-refresh",
            daemon=True,
        ).start()

    def _background_refresh(self) -> None:
        try:
            self._refresh(resolve_corpus_root(), force=True)
        finally:
            with self._refresh_lock:
                self._refreshing = False

    def _refresh(
        self,
        root: Path,
        *,
        force: bool,
    ) -> tuple[CorpusDocument, ...]:
        with self._lock:
            if (
                not force
                and root == self._root
                and time.monotonic() - self._loaded_at < self.ttl_seconds
            ):
                return self._documents
            documents: list[CorpusDocument] = []
            cached_files = self._file_cache if root == self._root else {}
            refreshed_cache: dict[str, tuple[int, int, CorpusDocument]] = {}
            if root.exists():
                for path in sorted(root.rglob("*.md"), key=lambda item: item.as_posix().lower()):
                    relative = path.relative_to(root)
                    if any(part.startswith(".") for part in relative.parts[:-1]):
                        continue
                    try:
                        relative_path = relative.as_posix()
                        stat = path.stat()
                        signature = (stat.st_mtime_ns, stat.st_size)
                        cached = cached_files.get(relative_path)
                        if cached and cached[:2] == signature:
                            documents.append(cached[2])
                            refreshed_cache[relative_path] = cached
                            continue
                        text = path.read_text(encoding="utf-8")
                        created, tags, references, tag_counts, entry_count = _metadata(
                            path, text
                        )
                        entries = parse_entries(text)
                        updated = datetime.fromtimestamp(stat.st_mtime)
                    except (OSError, UnicodeDecodeError):
                        continue
                    document = CorpusDocument(
                        relative_path=relative_path,
                        path=path,
                        name=path.name,
                        text=text,
                        created_at=created,
                        updated_at=updated,
                        tags=tags,
                        references=references,
                        excerpt=_excerpt(text),
                        tag_counts=tag_counts,
                        entry_count=entry_count,
                        entries=entries,
                        tag_entry_anchors=_first_tag_entry_anchors(entries),
                    )
                    documents.append(document)
                    refreshed_cache[relative_path] = (*signature, document)
            self._root = root
            self._documents = tuple(documents)
            self._file_cache = refreshed_cache
            self._loaded_at = time.monotonic()
            return self._documents

    def get(self, relative_path: str) -> CorpusDocument | None:
        normalized = (relative_path or "").replace("\\", "/")
        return next((doc for doc in self.documents() if doc.relative_path == normalized), None)


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _reference_markup(reference: "ReferenceLink") -> str:
    label = html.escape(reference.label, quote=False)
    href = html.escape(reference.href or "", quote=True)
    if reference.preview_kind:
        kind = html.escape(reference.preview_kind, quote=True)
        preview_url = html.escape(reference.preview_url, quote=True)
        media_url = html.escape(reference.media_url, quote=True)
        thumbnail = ""
        if reference.thumbnail_url:
            thumbnail_url = html.escape(reference.thumbnail_url, quote=True)
            fallback = "▶" if reference.preview_kind == "video" else "▧"
            thumbnail = (
                '<span class="corpus-reference-thumbnail">'
                f'<span class="corpus-reference-thumbnail-fallback" aria-hidden="true">{fallback}</span>'
                f'<img src="{thumbnail_url}" alt="">'
                "</span>"
            )
        return (
            f'<a href="{href}" class="corpus-reference-preview" '
            f'data-reference-preview data-preview-kind="{kind}" '
            f'data-preview-url="{preview_url}" data-media-url="{media_url}" '
            f'data-download-url="{href}">'
            f"{thumbnail}"
            f'<span class="corpus-reference-label">{label}</span>'
            '<span class="corpus-reference-action">'
            f'{"Play video" if reference.preview_kind == "video" else "Open viewer"}'
            "</span></a>"
        )
    attributes = (
        ' target="_blank" rel="noopener noreferrer"'
        if reference.kind == "external"
        else ""
    )
    return f'<a href="{href}"{attributes}>{label}</a>'


def format_hfl_markdown(
    source: str,
    reference_links: tuple["ReferenceLink", ...] | list["ReferenceLink"] | None = None,
) -> str:
    """Prepare canonical HFL fields for readable Markdown presentation.

    Source files remain untouched. Labels become bold paragraphs and indented
    reference bullets are normalized so the Markdown renderer treats them as
    a list instead of a code block.
    """
    links_by_source = {
        reference.source: reference
        for reference in (reference_links or ())
        if reference.source
        and reference.href
        and reference.kind in {"download", "external"}
    }
    sanitize_references = reference_links is not None
    output: list[str] = []
    in_references = False
    references_rendered = False
    for raw in (source or "").splitlines():
        field = _HFL_FIELD.match(raw)
        if field:
            label = _HFL_FIELD_LABELS[field.group(1).lower()]
            value = field.group(2).strip()
            if label == "References" and sanitize_references:
                in_references = True
                references_rendered = False
                continue
            if output and output[-1] != "":
                output.append("")
            output.append(f"**{label}:**" + (f" {value}" if value else ""))
            output.append("")
            in_references = label == "References"
            continue

        stripped = raw.strip()
        if in_references and stripped.startswith("- "):
            raw_reference = stripped[2:].strip()
            if sanitize_references:
                reference = links_by_source.get(raw_reference)
                if not reference:
                    continue
                if not references_rendered:
                    if output and output[-1] != "":
                        output.append("")
                    output.extend(["**References:**", ""])
                    references_rendered = True
                output.append(f"- {_reference_markup(reference)}")
            else:
                output.append(stripped)
            continue
        if stripped and not stripped.startswith("-"):
            in_references = False
        output.append(raw.rstrip())
    return "\n".join(output).strip() + "\n"


def common_tags(
    documents: tuple[CorpusDocument, ...], limit: int = 100
) -> list[tuple[str, int]]:
    """Return the most common document tags, ordered by count then name."""
    counts = Counter(tag for document in documents for tag in set(document.tags))
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]


def common_sources(documents: tuple[CorpusDocument, ...]) -> list[str]:
    """Return distinct nonblank entry sources in case-insensitive name order."""
    sources: dict[str, str] = {}
    for document in documents:
        for entry in document.entries:
            source = entry.source.strip()
            if source:
                sources.setdefault(source.casefold(), source)
    return sorted(sources.values(), key=str.casefold)


def normalize_source(value: str, sources: list[str] | tuple[str, ...]) -> str:
    """Return the canonical available source name, or All as an empty value."""
    needle = (value or "").strip().casefold()
    return next(
        (source for source in sources if source.casefold() == needle),
        "",
    )


def parse_search_query(query: str) -> tuple[tuple[str, ...], str]:
    """Split a space-delimited query into partial tags and a text phrase."""
    tokens = query.split()
    tags = tuple(
        dict.fromkeys(
            token[1:].casefold()
            for token in tokens
            if token.startswith("#") and len(token) > 1
        )
    )
    phrase = " ".join(
        token for token in tokens if not token.startswith("#")
    ).strip().casefold()
    return tags, phrase


def search_documents(
    documents: tuple[CorpusDocument, ...],
    *,
    query: str = "",
    date_field: str = "created",
    date_from: str = "",
    date_to: str = "",
    created_from: str = "",
    created_to: str = "",
    updated_from: str = "",
    updated_to: str = "",
    sort_order: str = "desc",
    source: str = "",
) -> list[CorpusDocument]:
    tag_needles, text_needle = parse_search_query(query)
    source_needle = (source or "").strip()
    if date_from or date_to:
        if date_field == "updated":
            updated_from, updated_to = date_from, date_to
        else:
            created_from, created_to = date_from, date_to
    c_from, c_to = parse_date(created_from), parse_date(created_to)
    u_from, u_to = parse_date(updated_from), parse_date(updated_to)

    results: list[CorpusDocument] = []
    for document in documents:
        if source_needle and not document.matching_entries(
            tag_needles,
            text_needle,
            source_needle,
        ):
            continue
        if text_needle and text_needle not in document.text.lower():
            continue
        if any(
            not any(needle in tag.casefold() for tag in document.tags)
            for needle in tag_needles
        ):
            continue
        if c_from and document.created_at.date() < c_from:
            continue
        if c_to and document.created_at.date() > c_to:
            continue
        if u_from and document.updated_at.date() < u_from:
            continue
        if u_to and document.updated_at.date() > u_to:
            continue
        results.append(document)
    return sorted(
        results,
        key=lambda item: (item.created_at, item.relative_path),
        reverse=sort_order != "asc",
    )


def build_tree(documents: tuple[CorpusDocument, ...]) -> dict:
    root = {"name": "Corpus", "path": "", "directories": {}, "files": []}
    for document in documents:
        node = root
        parts = Path(document.relative_path).parts
        if any(part.startswith(".") for part in parts[:-1]):
            continue
        for index, part in enumerate(parts[:-1]):
            current_path = Path(*parts[: index + 1]).as_posix()
            node = node["directories"].setdefault(
                part,
                {"name": part, "path": current_path, "directories": {}, "files": []},
            )
        node["files"].append(document)

    def directory_key(item: tuple[str, dict]) -> tuple[int, int, str]:
        name = item[0]
        folded = name.casefold()
        if folded in _MONTH_DIRECTORY_ORDER:
            return (0, _MONTH_DIRECTORY_ORDER[folded], "")
        return (1, -int(name), "") if name.isdigit() else (0, 0, folded)

    def finalize(node: dict) -> dict:
        files = sorted(
            node["files"],
            key=lambda item: (item.name.casefold(), item.relative_path.casefold()),
        )
        files.sort(key=lambda item: item.created_at, reverse=True)
        return {
            "name": node["name"],
            "path": node["path"],
            "directories": [
                finalize(child)
                for _, child in sorted(
                    node["directories"].items(), key=directory_key
                )
            ],
            "files": files,
        }

    return finalize(root)


def find_tree_node(tree: dict, relative_path: str) -> dict | None:
    normalized = (relative_path or "").strip("/")
    if not normalized:
        return tree
    for directory in tree["directories"]:
        if directory["path"] == normalized:
            return directory
        found = find_tree_node(directory, normalized)
        if found:
            return found
    return None


def shallow_tree(node: dict) -> dict:
    return {
        "name": node["name"],
        "path": node["path"],
        "directories": [
            {
                "name": directory["name"],
                "path": directory["path"],
                "directories": [],
                "files": [],
            }
            for directory in node["directories"]
        ],
        "files": node["files"],
    }


corpus_index = CorpusIndex(stale_while_revalidate=True)
