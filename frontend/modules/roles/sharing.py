"""Build citations only from explicitly selected, versioned owner evidence."""
import hashlib
import json
import re
from dataclasses import replace

from modules.roles import store


def sections(text):
    return [part.strip() for part in re.split(r'(?m)(?=^#{1,6} )', text) if part.strip()]


def linked_evidence(role):
    """Use the existing entity projection, including its secret filtering."""
    if not role.get('entity_ids'):
        return ()
    from modules.hfl_shares.router import _sharing_documents
    from modules.hfl_shares.models import ShareConfiguration, ALL_SOURCES
    from modules.hfl_shares.scope import build_snapshot
    from modules.hfl_corpus.secrets import normalize_secret_tags
    from modules.profile.store import get_profile_store
    configuration = ShareConfiguration(
        id='facet-entities', name=role['name'], sources=(ALL_SOURCES,),
        entity_ids=tuple(role['entity_ids']), references_enabled=False,
        activity={'sections': ['entries', 'actions', 'ideas', 'graph'], 'include_completed': True},
    )
    snapshot = build_snapshot(configuration, _sharing_documents((ALL_SOURCES,)),
        secret_tags=normalize_secret_tags(get_profile_store().get().secret_tags))
    graph = snapshot.activity.get('connections', {})
    labels = {node['id']: node['label'] for node in graph.get('nodes', [])
              if node['id'] in role['entity_ids']}
    related = {}
    for edge in graph.get('edges', []):
        for origin, target in ((edge['source'], edge['target']), (edge['target'], edge['source'])):
            if target in labels:
                related.setdefault(origin, set()).add(labels[target])
    return tuple(replace(entry, text=entry.text + (
        '\n\nLinked entities: ' + ', '.join(sorted(names)) if
        (names := related.get(entry.id, related.get('entry:' + entry.id, set()))) else ''
    )) for entry in snapshot.all_entries)


def history_text(revision):
    """A reviewable historical record; never include private journal drafts."""
    lines = [f"Facet revision {revision['revision']} · {revision.get('updated_at', '')}",
             f"Name: {revision['name']}",
             'Historical record, not necessarily the current state.',
             f"Linked Spaces: {len(revision.get('workspace_ids', []))}",
             f"Linked entities: {len(revision.get('entity_ids', []))}",
             'Soul:\n' + (revision.get('soul') or 'No Soul text saved.')]
    lines.extend('Attachment: ' + item['name'] + ' · ' + item.get('status', 'unknown')
                 for item in revision.get('files', []))
    lines.extend('Approved agent observation (inference): ' + item['text']
                 for item in revision.get('journal', []) if item.get('status') == 'approved')
    return '\n\n'.join(lines)


def choices():
    result = []
    runs = store.runs()
    for role in store.listing():
        if role.get('archived'):
            continue
        parts = [('soul-' + str(i), part.splitlines()[0].lstrip('# ')[:100], part, 'Owner-authored', None)
                 for i, part in enumerate(sections(role.get('soul', '')))]
        for item in role.get('files', []):
            if item.get('status') == 'ready':
                # Paragraph-sized excerpts let the owner omit private CV details.
                for i, part in enumerate(sections(item['text'])):
                    for j, start in enumerate(range(0, len(part), 3000)):
                        parts.append((f"file-{item['id']}-{i}-{j}", item['name'] + f' · excerpt {i+1}.{j+1}', part[start:start+3000], 'Extracted attachment', item))
        for item in role.get('journal', []):
            if item.get('status') == 'approved':
                # Private evidence links are not carried into the public projection.
                parts.append(('journal-' + item['id'], 'Approved observation', item['text'], 'Agent observation, owner-approved', None))
        for revision in store.history(role['id']):
            if revision['revision'] == role['revision']:
                continue
            parts.append((f"revision-{revision['revision']}", f"Revision {revision['revision']}",
                          history_text(revision), 'Revision history', None))
        for run in runs:
            for summary in run.get('roles', []):
                if summary['id'] != role['id']:
                    continue
                text = (f"Analysis on {run.get('created_at', '')}: {run.get('status', 'unknown')}\n"
                        f"Facet: {role['name']}\n{summary.get('selected', 0)} new or changed sources checked; "
                        f"{summary.get('observations', 0)} new observations.\n"
                        f"Coverage: {summary.get('coverage', 'Not recorded')}\n"
                        'Analysis metadata is not proof of skills or achievements. '
                        'Only separately selected approved observations provide analysis content.')
                parts.append(('analysis-' + run['id'], 'Analysis · ' + run.get('created_at', ''),
                              text, 'Analysis history', None))
        for entry in linked_evidence(role):
            digest = hashlib.sha256((entry.id + entry.text).encode()).hexdigest()[:24]
            parts.append(('activity-' + digest, entry.moment or entry.header or 'Linked activity',
                          f"{entry.header}\nSource: {entry.source}\n\n{entry.text}", 'Linked entity activity', None))
        for key, title, text, origin, file in parts:
            token = f"{role['id']}:{role['revision']}:{key}"
            result.append({'id': token, 'role_id': role['id'], 'revision': role['revision'], 'role': role['name'],
                           'color': role.get('color') if re.fullmatch(r'#[0-9a-fA-F]{6}', str(role.get('color', ''))) else '#3b82f6',
                           'title': title, 'text': text, 'origin': origin, 'file': file and {k: file[k] for k in ('id', 'name', 'digest')},
                           'workspace_ids': role.get('workspace_ids', [])})
    return result


def from_form(form, existing=None):
    selected = list(dict.fromkeys(form.getlist('persona_ids')))
    if len(selected) > 100:
        raise ValueError('Select at most 100 personal excerpts.')
    catalog = {item['id']: item for item in choices()}
    # A saved recipe can intentionally retain an old approved revision.
    previous = (existing.persona if existing else {}) or {}
    for item in previous.get('items', []):
        catalog.setdefault(item['id'], item)
    downloads = set(form.getlist('persona_downloads'))
    items = []
    for identity in selected:
        if identity not in catalog:
            raise ValueError('Personal context changed. Reload and review the selected role.')
        item = dict(catalog[identity])
        item['download'] = identity in downloads and bool(item.get('file'))
        items.append(item)
    if sum(len(item['text']) for item in items) > 120000:
        raise ValueError('Select no more than 120,000 characters of personal context.')
    if 'persona_context' in form:
        guidance = {'context': str(form.get('persona_context') or '').strip()}
        if len(guidance['context']) > 20000:
            raise ValueError('Share context must be at most 20,000 characters.')
    else:
        # Older clients can still submit the original structured guidance.
        guidance = {key: str(form.get('persona_' + key) or '').strip() for key in ('company', 'target_role', 'job_description', 'audience', 'tone', 'icebreakers')}
        if any(len(value) > (12000 if key == 'job_description' else 1000) for key, value in guidance.items()):
            raise ValueError('Opportunity guidance is too long.')
    suggestions = previous.get('suggestions', {'mode': 'automatic', 'questions': []})
    if 'suggestion_mode' in form:
        mode = str(form.get('suggestion_mode') or '')
        questions = list(dict.fromkeys(line.strip() for line in str(form.get('suggestion_questions') or '').splitlines() if line.strip()))
        if mode not in ('off', 'custom', 'automatic'):
            raise ValueError('Choose a valid suggested-question mode.')
        if len(questions) > 5 or any(len(question) > 240 for question in questions):
            raise ValueError('Use at most five suggested questions, with 240 characters each.')
        if mode == 'custom' and not questions:
            raise ValueError('Add at least one custom question or choose Off.')
        suggestions = {'mode': mode, 'questions': questions}
    return {'items': items, 'guidance': guidance, 'suggestions': suggestions}


def project(configuration, snapshot):
    from modules.hfl_shares.models import SnapshotEntry, SnapshotReference
    entries = []
    for i, item in enumerate(configuration.persona.get('items', [])):
        references = ()
        if item.get('download') and item.get('file'):
            file = item['file']
            references = (SnapshotReference(id='persona-' + hashlib.sha256(item['id'].encode()).hexdigest()[:24],
                label=file['name'], kind='persona_attachment', target=json.dumps({'role_id': item['role_id'], **file}), enabled=True),)
        entries.append(SnapshotEntry(id='persona:' + item['id'], citation=f'S{len(snapshot.all_entries)+i+1}',
            relative_path='', anchor='', header=item['title'], moment=item['role'] + ' · ' + item['title'],
            what_happened=item['text'], source='persona', tags=(),
            text=f"{item['role']} — {item['title']}\n{item['origin']} · revision {item['revision']}\n\n{item['text']}", references=references))
    return replace(snapshot, persona_entries=tuple(entries), opportunity=configuration.persona.get('guidance', {}),
                   suggestion_settings=configuration.persona.get('suggestions', {}),
                   estimated_chars=snapshot.estimated_chars + sum(len(e.text) for e in entries),
                   available_references=snapshot.available_references + sum(len(e.references) for e in entries),
                   enabled_reference_ids=snapshot.enabled_reference_ids + tuple(r.id for e in entries for r in e.references))


def download(reference):
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    value = json.loads(reference.target)
    attachments = store.attachment_store()
    manifest = attachments.get('role:' + value['role_id'], value['id'])
    if manifest['digest'] != value['digest']:
        raise HTTPException(404, 'Attachment unavailable.')
    return FileResponse(attachments.path(manifest), filename=manifest['name'], media_type='application/octet-stream',
                        headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
