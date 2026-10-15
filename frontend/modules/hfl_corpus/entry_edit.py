"""Targeted entry edits: preserve the surrounding document and unknown metadata."""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from modules.hfl_corpus.corpus import _HEADER, parse_entries, corpus_index
from modules.hfl_corpus.document_edit import DocumentConflictError, update_document_text
from modules.hfl_corpus.entry_create import (
    MAX_UPLOAD_FILES, MAX_UPLOAD_FILE_BYTES, MAX_UPLOAD_TOTAL_BYTES,
    _available_upload_names, resolve_upload_inbox,
)

# Unknown metadata labels also terminate editable fields so they survive edits.
_FIELD = re.compile(r'^([A-Za-z][A-Za-z _-]{0,60}):[ \t]*(.*)$', re.MULTILINE)
LABELS = {'moment': 'Moment', 'what_happened': 'What happened',
          'why_it_stayed': 'Why it stayed', 'possible_use': 'Possible use',
          'tags': 'Tags', 'references': 'References'}


class EntryUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    anchor: str = Field(min_length=1, max_length=200)
    entry_id: str = Field(default='', max_length=200)
    expected_updated_at: str = Field(min_length=1, max_length=100)
    date: str = Field(default='', max_length=10)
    time: str = Field(default='', max_length=15)
    moment: str = Field(max_length=20_000)
    what_happened: str = Field(max_length=2_000_000)
    why_it_stayed: str = Field(default='', max_length=100_000)
    possible_use: str = Field(default='', max_length=100_000)
    tags: str = Field(default='', max_length=20_000)
    references: list[str] = Field(default_factory=list, max_length=1000)


def locate(document, anchor):
    entries = parse_entries(document.text)
    index = next((i for i, entry in enumerate(entries) if entry.anchor == anchor), None)
    if index is None:
        raise ValueError('Entry not found. Reload the document and try again.')
    headings = list(_HEADER.finditer(document.text))
    start = headings[index].start()
    end = headings[index + 1].start() if index + 1 < len(headings) else len(document.text)
    return entries[index], start, end


def fields(block):
    matches = list(_FIELD.finditer(block))
    return {match.group(1).casefold(): (match.start(), matches[i + 1].start() if i + 1 < len(matches) else len(block),
            block[match.start():matches[i + 1].start() if i + 1 < len(matches) else len(block)].split(':', 1)[1].strip())
            for i, match in enumerate(matches)}


def entry_details(document, anchor):
    entry, start, end = locate(document, anchor)
    values = fields(document.text[start:end])
    get = lambda name: values.get(name.casefold(), (0, 0, ''))[2]
    try:
        when = datetime.fromisoformat(entry.header)
    except ValueError:
        when = None
    result = {key: get(label) for key, label in LABELS.items()}
    result['references'] = [line.strip()[2:].strip() for line in get('References').splitlines() if line.strip().startswith('- ')]
    return {**result, 'anchor': anchor, 'entry_id': get('Entry ID').splitlines()[0] if get('Entry ID') else '',
            'source': entry.source, 'machine': get('Machine'),
            'date': when.strftime('%Y-%m-%d') if when else '',
            'time': when.strftime('%H:%M:%S') if when else '',
            'expected_updated_at': document.updated_at.isoformat()}


def replace_field(block, label, value):
    existing = fields(block).get(label.casefold())
    if existing and existing[2] == value.strip():
        return block
    replacement = f'{label}: {value}\n\n'
    if existing:
        start, end, _ = existing
        return block[:start] + replacement + block[end:]
    return block.rstrip() + '\n\n' + replacement


def apply_update(document, payload):
    if document.updated_at.isoformat() != payload.expected_updated_at:
        raise DocumentConflictError('This document changed. Reload it before saving this entry.')
    original = entry_details(document, payload.anchor)
    if original['entry_id'] != payload.entry_id:
        raise DocumentConflictError('This entry changed. Reload it before saving.')
    entry, start, end = locate(document, payload.anchor)
    block = document.text[start:end]
    if (payload.date, payload.time) != (original['date'], original['time']):
        try:
            when = datetime.fromisoformat(f'{payload.date}T{payload.time}')
        except ValueError as exc:
            raise ValueError('Enter a valid date and time.') from exc
        if when.tzinfo is not None:
            raise ValueError('Enter a local date and time.')
        block = _HEADER.sub('## ' + when.isoformat(sep=' ', timespec='seconds'), block, count=1)
    for key, label in LABELS.items():
        value = getattr(payload, key)
        if value == original[key]:
            continue
        if key == 'references':
            if any('\n' in ref or '\r' in ref or len(ref) > 20_000 for ref in value):
                raise ValueError('Each reference must be on one line.')
            value = '\n' + '\n'.join('- ' + ref.strip() for ref in dict.fromkeys(value) if ref.strip())
        else:
            if _HEADER.search(value) or _FIELD.search(value):
                raise ValueError(f'{label} cannot contain entry headings or unindented metadata labels. Indent those lines.')
            if key == 'tags':
                value = ' '.join('#' + tag.lstrip('#') for tag in value.split())
        block = replace_field(block, label, value)
    identity = original['entry_id'] or 'hfl-' + uuid.uuid4().hex
    if not original['entry_id']:
        block = replace_field(block, 'Entry ID', identity)
    return document.text[:start] + block + document.text[end:], identity


def sync_entry(text, anchor):
    from workflows.hfl.dto import HflEntry
    from workflows.hfl.es_store import index_hfl_entry
    entry = next(entry for entry in parse_entries(text) if entry.anchor == anchor)
    header, body = entry.text.split('\n', 1)
    parsed = HflEntry.from_markdown(header, body)
    return bool(index_hfl_entry(parsed, source=parsed.source, synthesized=bool(parsed.synthesized)))


async def save_entry(document, payload, uploads, *, corpus_dir, inbox_dir=None):
    # Validate all entry changes before accepting files; the document writer rechecks
    # the version under its lock after staging uploads.
    text, identity = apply_update(document, payload)
    if len(uploads) > MAX_UPLOAD_FILES:
        raise ValueError('Select no more than 50 files.')
    created = []
    saved = False
    try:
        if uploads:
            target = (inbox_dir or resolve_upload_inbox()).resolve() / 'uploads' / 'entry-edits' / uuid.uuid4().hex
            names = _available_upload_names([file.filename or 'upload' for file in uploads], target_dir=target)
            target.mkdir(parents=True)
            total = 0
            for upload, name in zip(uploads, names, strict=True):
                path = target / name
                created.append(path)
                size = 0
                with path.open('xb') as handle:
                    while chunk := await upload.read(1024 * 1024):
                        size += len(chunk)
                        total += len(chunk)
                        if size > MAX_UPLOAD_FILE_BYTES or total > MAX_UPLOAD_TOTAL_BYTES:
                            raise ValueError('Attachment upload exceeds the configured size limit.')
                        handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
            payload = payload.model_copy(update={'references': [*payload.references, *(str(path) for path in created)]})
            text, identity = apply_update(document, payload)
        update_document_text(document, text, corpus_dir=corpus_dir, expected_updated_at=payload.expected_updated_at)
        saved = True
        old_entries = parse_entries(document.text)
        index = next(i for i, item in enumerate(old_entries) if item.anchor == payload.anchor)
        anchor = parse_entries(text)[index].anchor
        corpus_index.documents(force=True)
        warning = ''
        try:
            if not sync_entry(text, anchor):
                warning = 'Entry saved, but search synchronization failed. Search results may be stale.'
        except Exception:
            warning = 'Entry saved, but search synchronization failed. Search results may be stale.'
        return {'updated': True, 'entry_id': identity, 'anchor': anchor, 'warning': warning}
    finally:
        if not saved:
            for path in created:
                path.unlink(missing_ok=True)
        for upload in uploads:
            await upload.close()
