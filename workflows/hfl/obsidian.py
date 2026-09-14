"""One-way, conflict-aware Markdown export. User-owned files are never overwritten."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

import hashlib

def content_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                            dir=path.parent, delete=False) as stream:
        stream.write(text)
        temporary = stream.name
    try:
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def export_vault(entries: list[dict], vault: Path) -> dict:
    """Export a complete selected scope; modified withdrawals remain visible conflicts."""
    from filelock import FileLock
    vault = Path(vault).resolve()
    vault.mkdir(parents=True, exist_ok=True)
    with FileLock(vault / '.harqis-export.lock', timeout=30):
        return _export_vault(entries, vault)


def _export_vault(entries: list[dict], vault: Path) -> dict:
    vault = Path(vault).resolve()
    vault.mkdir(parents=True, exist_ok=True)
    manifest_path = vault / '.harqis-export.json'
    previous = json.loads(manifest_path.read_text('utf-8')) if manifest_path.exists() else {}
    identity_path = vault / '.harqis-identities.json'
    identities = json.loads(identity_path.read_text('utf-8')) if identity_path.exists() else {}
    current_identities = {}
    generated: dict[str, str] = {}
    days: dict[str, list[str]] = {}
    entities: dict[str, list[str]] = {}
    for entry in entries:
        title_part = re.sub(r'[^\w -]', '', entry['title'], flags=re.UNICODE).strip()[:70] or 'Entry'
        stem = identities.get(entry['id']) or title_part + ' -- ' + content_hash(entry['id'])[:12]
        if re.search(r'[\x00-\x1f<>:"/\\|?*\[\]#]', stem) or stem in {'.', '..'}:
            raise ValueError('Unsafe generated note identity')
        current_identities[entry['id']] = stem
        target = f'Entries/{stem}.md'
        title = entry['title'].replace('\n', ' ')
        links = []
        for kind, names in entry.get('entities', {}).items():
            if kind == 'urls':
                continue
            for name in names:
                entity_stem = _entity_stem(kind + ':' + name)
                links.append(f'[[Entities/{entity_stem}]]')
                entities.setdefault(f'{kind}:{name}', []).append(f'[[Entries/{stem}]]')
        metadata = '\n'.join(f'{key}: {json.dumps(value, ensure_ascii=False)}' for key, value in {
            'harqis_id': entry['id'], 'title': title, 'source': entry.get('source', ''),
            'date': entry.get('date', ''), 'tags': entry.get('tags', []),
            'harqis_generated': True}.items())
        generated[target] = (f'---\n{metadata}\n---\n\n# {title}\n\n'
                             + (f"[Open authenticated HARQIS source]({entry['ref']})\n\n" if entry.get('ref') else '') +
                             f"{entry['text']}\n\n" + '\n'.join(sorted(set(links))) + '\n')
        day = entry.get('date', '')[:10]
        if day:
            from datetime import date
            date.fromisoformat(day)
            days.setdefault(day, []).append(f'[[Entries/{stem}]]')
    for day, links in days.items():
        generated[f'Daily/{day}.md'] = f'# {day}\n\n' + '\n'.join(sorted(set(links))) + '\n'
    for entity, links in entities.items():
        generated[f'Entities/{_entity_stem(entity)}.md'] = (
            f'# {entity}\n\n' + '\n'.join(sorted(set(links))) + '\n')
    result = dict(written=0, unchanged=0, withdrawn=0, conflicts=[])
    manifest = dict(previous)
    for relative in sorted(set(previous) | set(generated)):
        parts = Path(relative).parts
        if len(parts) != 2 or parts[0] not in {'Entries', 'Daily', 'Entities'} or not parts[1].endswith('.md'):
            raise ValueError('Export manifest contains a non-generated path')
        target = (vault / relative).resolve()
        if not target.is_relative_to(vault) or target == vault:
            raise ValueError('Export manifest path escapes vault')
        actual = content_hash(target.read_text('utf-8')) if target.exists() else None
        wanted = generated.get(relative)
        digest = content_hash(wanted) if wanted is not None else None
        if actual is not None and actual != previous.get(relative) and actual != digest:
            result['conflicts'].append({'path': relative,
                                        'reason': 'withdrawal' if wanted is None else 'local-edit'})
            continue
        if wanted is None:
            if target.exists():
                target.unlink()
                result['withdrawn'] += 1
            manifest.pop(relative, None)
        elif actual == digest:
            result['unchanged'] += 1
            manifest[relative] = digest
        else:
            _atomic_write(target, wanted)
            manifest[relative] = digest
            result['written'] += 1
    _atomic_write(manifest_path, json.dumps(manifest, indent=2, sort_keys=True))
    _atomic_write(identity_path, json.dumps(current_identities, indent=2, sort_keys=True, ensure_ascii=False))
    _atomic_write(vault / '.harqis-conflicts.json', json.dumps(result['conflicts'], indent=2))
    return result


def _entity_stem(entity: str) -> str:
    label = re.sub(r'[^\w -]', '', entity.replace(':', ' - ', 1), flags=re.UNICODE).strip()[:80]
    return label + ' -- ' + content_hash(entity)[:12]
