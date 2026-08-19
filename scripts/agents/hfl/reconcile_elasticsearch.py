#!/usr/bin/env python3
"""Reconcile the rebuildable HFL Elasticsearch projection from Markdown.

The command is read-only by default. ``--apply`` bulk-upserts missing or stale
canonical entries; it never deletes Elasticsearch documents or changes the
Markdown corpus.

Usage:
    python scripts/agents/hfl/reconcile_elasticsearch.py
    python scripts/agents/hfl/reconcile_elasticsearch.py --apply
    python scripts/agents/hfl/reconcile_elasticsearch.py --index harqis-hfl-entries-v2 --apply
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_INDEX = "harqis-hfl-entries"
_HEADER = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_STABLE_FIELDS = (
    "schema_version",
    "source",
    "when",
    "entry_date",
    "moment",
    "what_happened",
    "why_it_stayed",
    "possible_use",
    "tags",
    "references",
    "machine",
    "entry_id",
    "synthesized",
)


@dataclass(frozen=True)
class CorpusScan:
    documents: dict[str, dict[str, Any]]
    files: int
    invalid_entries: int
    duplicate_ids: int


@dataclass(frozen=True)
class Reconciliation:
    missing_ids: tuple[str, ...]
    stale_ids: tuple[str, ...]
    unchanged: int

    @property
    def changed_ids(self) -> tuple[str, ...]:
        return self.missing_ids + self.stale_ids


class ExistingDocuments(dict[str, dict[str, Any]]):
    """Live documents keyed by canonical entry_id, with their actual ES IDs."""

    def __init__(self) -> None:
        super().__init__()
        self.actual_ids: dict[str, str] = {}

    def add(self, actual_id: str, source: dict[str, Any]) -> None:
        canonical_id = str(source.get("entry_id") or actual_id)
        if canonical_id in self and self.actual_ids[canonical_id] != actual_id:
            raise ValueError(
                f"multiple Elasticsearch documents claim entry_id {canonical_id}"
            )
        self[canonical_id] = source
        self.actual_ids[canonical_id] = actual_id


def _same_projection(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return all(left.get(field) == right.get(field) for field in _STABLE_FIELDS)


def scan_corpus(corpus_root: Path) -> CorpusScan:
    """Build canonical ES documents from all valid Markdown entry blocks."""
    from workflows.hfl.dto import HflEntry
    from workflows.hfl.es_store import hfl_document

    root = Path(corpus_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("The HFL corpus directory does not exist.")
    documents: dict[str, dict[str, Any]] = {}
    files = invalid = duplicates = 0
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        files += 1
        text = path.read_text(encoding="utf-8")
        matches = list(_HEADER.finditer(text))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            entry = HflEntry.from_markdown(match.group(1), text[match.end():end])
            if not (
                entry.when
                and entry.moment
                and entry.source
                and entry.machine
                and entry.entry_id
            ):
                invalid += 1
                continue
            doc = hfl_document(entry, entry.source)
            synthesized_explicit = (
                entry.synthesized is not None or "synthesized" in entry.tags
            )
            doc["synthesized"] = (
                entry.synthesized
                if entry.synthesized is not None
                else "synthesized" in entry.tags
            )
            doc["_canonical_synthesized_explicit"] = synthesized_explicit
            doc["_canonical_when_precision"] = (
                "second"
                if re.search(r"\d{2}:\d{2}:\d{2}", match.group(1))
                else "minute"
            )
            if entry.entry_id in documents:
                duplicates += 1
            documents[entry.entry_id] = doc
    return CorpusScan(documents, files, invalid, duplicates)


def fetch_existing(client: Any, index: str, ids: list[str]) -> ExistingDocuments:
    """Resolve canonical IDs through either ES ``_id`` or ``entry_id``."""
    encoded = urllib.parse.quote(index, safe="-_.")
    existing = ExistingDocuments()
    for offset in range(0, len(ids), 500):
        batch = ids[offset:offset + 500]
        response = client._request(  # shared stdlib client; no secrets logged
            "POST",
            f"/{encoded}/_mget",
            {"ids": batch},
        )
        for row in response.get("docs", []):
            source = row.get("_source")
            if row.get("found") and isinstance(source, dict):
                existing.add(str(row.get("_id") or ""), source)
    unresolved = [entry_id for entry_id in ids if entry_id not in existing]
    for offset in range(0, len(unresolved), 500):
        batch = unresolved[offset:offset + 500]
        response = client._request(
            "POST", f"/{encoded}/_search",
            {"size": len(batch) * 2, "_source": True,
             "query": {"terms": {"entry_id.keyword": batch}}},
        )
        for hit in response.get("hits", {}).get("hits", []):
            source = hit.get("_source")
            if isinstance(source, dict) and source.get("entry_id") in batch:
                existing.add(str(hit.get("_id") or ""), source)
    return existing


def preserve_existing_legacy_metadata(
    expected: dict[str, dict[str, Any]],
    existing: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Keep richer live metadata when legacy Markdown could not encode it."""
    merged_documents: dict[str, dict[str, Any]] = {}
    for doc_id, document in expected.items():
        merged = dict(document)
        synthesized_explicit = bool(
            merged.pop("_canonical_synthesized_explicit", False)
        )
        when_precision = str(merged.pop("_canonical_when_precision", "minute"))
        current = existing.get(doc_id)
        if current:
            if not synthesized_explicit and isinstance(current.get("synthesized"), bool):
                merged["synthesized"] = current["synthesized"]
            current_when = str(current.get("when") or "")
            expected_when = str(merged.get("when") or "")
            try:
                current_dt = datetime.fromisoformat(current_when.replace("Z", "+00:00"))
                expected_dt = datetime.fromisoformat(expected_when.replace("Z", "+00:00"))
            except ValueError:
                current_dt = expected_dt = None
            if when_precision == "minute" and current_dt and expected_dt and (
                current_dt.year,
                current_dt.month,
                current_dt.day,
                current_dt.hour,
                current_dt.minute,
            ) == (
                expected_dt.year,
                expected_dt.month,
                expected_dt.day,
                expected_dt.hour,
                expected_dt.minute,
            ):
                merged["when"] = current_when
        merged_documents[doc_id] = merged
    return merged_documents


def compare_projection(
    expected: dict[str, dict[str, Any]],
    existing: dict[str, dict[str, Any]],
) -> Reconciliation:
    missing: list[str] = []
    stale: list[str] = []
    unchanged = 0
    for doc_id, document in expected.items():
        current = existing.get(doc_id)
        if current is None:
            missing.append(doc_id)
        elif not _same_projection(document, current):
            stale.append(doc_id)
        else:
            unchanged += 1
    return Reconciliation(tuple(missing), tuple(stale), unchanged)


def bulk_upsert(
    client: Any,
    index: str,
    documents: dict[str, dict[str, Any]],
    ids: tuple[str, ...],
    actual_ids: dict[str, str] | None = None,
) -> None:
    lines: list[str] = []
    for doc_id in ids:
        target_id = (actual_ids or {}).get(doc_id, doc_id)
        lines.append(json.dumps({"index": {"_index": index, "_id": target_id}}))
        lines.append(json.dumps(documents[doc_id], ensure_ascii=False))
    if not lines:
        return
    response = client._request(
        "POST",
        "/_bulk",
        raw_body=("\n".join(lines) + "\n").encode("utf-8"),
        content_type="application/x-ndjson",
    )
    if response.get("errors"):
        raise RuntimeError("Elasticsearch rejected one or more HFL documents.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Bulk-upsert changed entries.")
    parser.add_argument("--corpus", help="Override the configured HFL corpus directory.")
    parser.add_argument(
        "--index",
        default=os.environ.get("HFL_ES_INDEX", "").strip() or DEFAULT_INDEX,
        help=f"Target index (default: {DEFAULT_INDEX}).",
    )
    args = parser.parse_args()

    from scripts.agents.hfl.migrate_references import (
        _load_env_file,
        elasticsearch_client_from_env,
        resolve_corpus_root,
    )

    _load_env_file()
    try:
        scan = scan_corpus(resolve_corpus_root(args.corpus))
        client = elasticsearch_client_from_env()
        current = fetch_existing(client, args.index, list(scan.documents))
        documents = preserve_existing_legacy_metadata(scan.documents, current)
        reconciliation = compare_projection(documents, current)
        if args.apply:
            bulk_upsert(
                client,
                args.index,
                documents,
                reconciliation.changed_ids,
                current.actual_ids,
            )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Reconciliation failed: {exc}", file=sys.stderr)
        return 1

    mode = "applied" if args.apply else "dry-run"
    print(f"HFL Elasticsearch reconciliation ({mode})")
    print(f"  Markdown files scanned: {scan.files}")
    print(f"  Canonical entries: {len(scan.documents)}")
    print(f"  Missing documents: {len(reconciliation.missing_ids)}")
    print(f"  Stale documents: {len(reconciliation.stale_ids)}")
    print(f"  Unchanged documents: {reconciliation.unchanged}")
    print(f"  Invalid legacy entries skipped: {scan.invalid_entries}")
    print(f"  Duplicate entry IDs: {scan.duplicate_ids}")
    if reconciliation.changed_ids:
        print("  Changed entry IDs:")
        for entry_id in reconciliation.changed_ids:
            print(f"    - {entry_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
