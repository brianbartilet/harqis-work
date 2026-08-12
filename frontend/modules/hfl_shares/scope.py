"""Build sanitized, source-first snapshots from the Activity Corpus."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import replace
from datetime import date, datetime

from config import get_settings
from modules.hfl_corpus.corpus import CorpusDocument, resolve_corpus_root
from modules.hfl_shares.models import (
    ALL_SOURCES,
    ScopeSnapshot,
    ShareConfiguration,
    SnapshotEntry,
    SnapshotReference,
    utc_now,
)
from services.safe_paths import (
    allowed_reference_roots,
    load_download_token,
    resolve_reference,
)


_ENTRY_ID = re.compile(r"^\s*Entry ID:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_REFERENCE_LINE = re.compile(r"^\s*[-*•]\s+(.+?)\s*$")
_FIELD_LINE = re.compile(
    r"^\s*(Source|Machine|Entry ID|Moment|What happened|Why it stayed|Possible use|Tags|References):",
    re.IGNORECASE,
)
_WINDOWS_PATH = re.compile(r"\b[A-Za-z]:\\[^\s<>\"']+")
_UNIX_PATH = re.compile(r"(?<!:)\/(?:Users|Volumes|home|srv|etc|var)\/[^\s<>\"']+")


def _entry_key(document: CorpusDocument, anchor: str, text: str) -> str:
    match = _ENTRY_ID.search(text or "")
    if match:
        return match.group(1).strip()
    digest = hashlib.sha256(
        f"{document.relative_path}#{anchor}".encode("utf-8")
    ).hexdigest()[:20]
    return f"legacy-{digest}"


def _entry_datetime(header: str) -> datetime | None:
    raw = (header or "").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _entry_date(header: str) -> date | None:
    parsed = _entry_datetime(header)
    return parsed.date() if parsed else None


def _sanitize_entry_text(text: str) -> str:
    output: list[str] = []
    suppress_references = False
    for raw in (text or "").splitlines():
        field = _FIELD_LINE.match(raw)
        if field:
            label = field.group(1).casefold()
            suppress_references = label == "references"
            if label in {"machine", "entry id", "references"}:
                continue
        elif suppress_references:
            if _REFERENCE_LINE.match(raw.strip()) or not raw.strip():
                continue
            suppress_references = False
        safe = _WINDOWS_PATH.sub("[local path]", raw)
        safe = _UNIX_PATH.sub("[local path]", safe)
        output.append(safe.rstrip())
    return "\n".join(output).strip()


def _raw_references(entry_text: str) -> tuple[str, ...]:
    references: list[str] = []
    collecting = False
    for raw in (entry_text or "").splitlines():
        field = _FIELD_LINE.match(raw)
        if field:
            collecting = field.group(1).casefold() == "references"
            continue
        if collecting:
            bullet = _REFERENCE_LINE.match(raw.strip())
            if bullet:
                references.append(bullet.group(1).strip())
                continue
            if raw.strip():
                collecting = False
    return tuple(dict.fromkeys(references))


def _references(
    document: CorpusDocument,
    entry_id: str,
    entry_text: str,
) -> tuple[SnapshotReference, ...]:
    if not document.path:
        return ()
    corpus_root = resolve_corpus_root()
    roots = allowed_reference_roots(corpus_root)
    links: list[SnapshotReference] = []
    for raw in _raw_references(entry_text):
        resolved = resolve_reference(
            raw,
            source_document=document.path,
            corpus_root=corpus_root,
        )
        target = ""
        label = resolved.label
        if resolved.kind == "external" and resolved.href:
            target = resolved.href
        elif resolved.kind == "download" and resolved.href:
            token = resolved.href.rsplit("/", 2)[-2]
            path = load_download_token(token, roots)
            if path:
                target = str(path)
                label = path.name
        if not target:
            continue
        reference_id = hashlib.sha256(
            f"{entry_id}\0{raw}".encode("utf-8")
        ).hexdigest()[:24]
        links.append(
            SnapshotReference(
                id=reference_id,
                label=label,
                kind=resolved.kind,
                target=target,
            )
        )
    return tuple(links)


def build_snapshot(
    configuration: ShareConfiguration,
    documents: tuple[CorpusDocument, ...],
    *,
    enabled_reference_ids: tuple[str, ...] | None = None,
    disabled_reference_ids: tuple[str, ...] = (),
) -> ScopeSnapshot:
    all_sources = ALL_SOURCES in configuration.sources
    sources = {
        item.casefold()
        for item in configuration.sources
        if item != ALL_SOURCES
    }
    tags = {item.lstrip("#").casefold() for item in configuration.tags}
    topic_terms = tuple(
        term.casefold()
        for term in re.findall(r"[\w-]+", configuration.topic)
        if len(term) > 1
    )
    start = date.fromisoformat(configuration.date_from) if configuration.date_from else None
    end = date.fromisoformat(configuration.date_to) if configuration.date_to else None
    enabled = (
        None
        if enabled_reference_ids is None
        else set(enabled_reference_ids)
    )
    disabled = set(disabled_reference_ids)
    entries: list[SnapshotEntry] = []
    dates: list[date] = []
    available_references = 0
    missing_sources = set() if all_sources else set(sources)
    max_chars = max(1, get_settings().hfl_share_max_snapshot_chars)
    used_chars = 0
    truncated = False

    ordered_documents = sorted(
        documents,
        key=lambda document: (
            document.created_at.replace(tzinfo=None)
            if document.created_at
            else datetime.min
        ),
        reverse=True,
    )
    for document in ordered_documents:
        ordered_entries = sorted(
            document.entries,
            key=lambda entry: _entry_datetime(entry.header) or datetime.min,
            reverse=True,
        )
        for entry in ordered_entries:
            if not all_sources and entry.source.casefold() not in sources:
                continue
            missing_sources.discard(entry.source.casefold())
            entry_id = _entry_key(document, entry.anchor, entry.text)
            if tags and not tags.issubset({tag.casefold() for tag in entry.tags}):
                continue
            when = _entry_date(entry.header)
            if start and (not when or when < start):
                continue
            if end and (not when or when > end):
                continue
            sanitized_text = _sanitize_entry_text(entry.text)
            searchable = sanitized_text.casefold()
            if topic_terms and not all(term in searchable for term in topic_terms):
                continue
            entry_chars = len(sanitized_text)
            if used_chars + entry_chars > max_chars:
                if not entries:
                    raise ValueError(
                        "The newest matching entry exceeds the snapshot size limit."
                    )
                truncated = True
                break
            references = _references(document, entry_id, entry.text)
            available_references += len(references)
            if not configuration.references_enabled:
                references = ()
            else:
                references = tuple(
                    replace(
                        item,
                        enabled=(
                            item.id not in disabled
                            if enabled is None
                            else item.id in enabled
                        ),
                    )
                    for item in references
                )
            if when:
                dates.append(when)
            entries.append(
                SnapshotEntry(
                    id=entry_id,
                    citation=f"S{len(entries) + 1}",
                    relative_path=document.relative_path,
                    anchor=entry.anchor,
                    header=entry.header,
                    moment=entry.moment,
                    what_happened=entry.what_happened,
                    source=entry.source,
                    tags=entry.tags,
                    text=sanitized_text,
                    references=references,
                )
            )
            used_chars += entry_chars
        if truncated:
            break

    source_counts = Counter(entry.source for entry in entries)
    tag_counts = Counter(tag for entry in entries for tag in set(entry.tags))
    warnings: list[str] = []
    if missing_sources:
        warnings.append(
            "Unavailable sources: " + ", ".join(sorted(missing_sources))
        )
    if len(entries) > 250:
        warnings.append("This is a broad scope with more than 250 entries.")
    if truncated:
        warnings.append(
            "Older matching entries were omitted after the snapshot reached "
            "its 10-million-character limit."
        )
    if available_references and not configuration.references_enabled:
        warnings.append("References exist but sharing is disabled.")
    if not entries:
        warnings.append("No corpus entries match this configuration.")
    return ScopeSnapshot(
        entries=tuple(entries),
        created_at=utc_now().isoformat(),
        sources=(
            tuple(sorted(source_counts, key=str.casefold))
            if all_sources
            else configuration.sources
        ),
        filters={
            "tags": list(configuration.tags),
            "date_from": configuration.date_from,
            "date_to": configuration.date_to,
            "topic": configuration.topic,
        },
        source_counts=dict(source_counts),
        tag_counts=dict(tag_counts.most_common(20)),
        earliest=min(dates).isoformat() if dates else "",
        latest=max(dates).isoformat() if dates else "",
        estimated_chars=used_chars,
        available_references=available_references,
        enabled_reference_ids=tuple(
            sorted(
                reference.id
                for entry in entries
                for reference in entry.references
                if reference.enabled
            )
        ),
        warnings=tuple(warnings),
        context_prompt=configuration.context_prompt,
        recipient=configuration.recipient,
    )


def suggested_prompts(
    snapshot: ScopeSnapshot,
    owner_name: str = "P",
) -> tuple[str, ...]:
    if not snapshot.entries:
        return ()
    owner = owner_name.strip() or "P"
    suggestions = [
        f"What is {owner} currently working on?",
        f"Can you curate interview questions for me from {owner}'s work?",
    ]
    travel_terms = {
        "travel", "trip", "japan", "place", "places", "location", "holiday"
    }
    if travel_terms.intersection(tag.casefold() for tag in snapshot.tag_counts):
        suggestions.append(f"Show me places {owner} visited over the past year.")
    for source in list(snapshot.source_counts)[:1]:
        suggestions.append(f"What stands out from {owner}'s {source} activity?")
    for tag in list(snapshot.tag_counts)[:1]:
        suggestions.append(f"What does #{tag} reveal about {owner}'s work?")
    return tuple(dict.fromkeys(suggestions))[:5]


def snapshot_entry(snapshot: ScopeSnapshot, entry_id: str) -> SnapshotEntry | None:
    return next((entry for entry in snapshot.entries if entry.id == entry_id), None)
