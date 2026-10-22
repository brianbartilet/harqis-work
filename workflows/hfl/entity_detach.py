"""Selective, audited splits of a merge tree. Original merge audits remain immutable."""
import copy
import json

from workflows.hfl import entity_merges, entity_matching
from workflows.hfl.entity_store import digest, get_store


def replace_inherited(text, before, after):
    """Replace a whole unchanged inherited section; edited prose remains curated."""
    padded = '\n\n' + text + '\n\n'
    needle = '\n\n' + before + '\n\n'
    if padded.count(needle) == 1:
        return padded.replace(needle, '\n\n' + after + '\n\n' if after else '\n\n', 1).strip('\n')
    return text


def tree(db, identity):
    if db.execute('SELECT 1 FROM decisions WHERE alias=? AND active=1', (identity,)).fetchone():
        raise ValueError('Open the active outer merged entity')
    groups = {r['id']: dict(r) for r in db.execute('SELECT * FROM entity_merges WHERE active=1')}
    if identity not in groups:
        raise ValueError('No active merge exists for this entity')
    nodes, paths = {}, {}
    stack = [(identity, [])]
    while stack:
        key, path = stack.pop()
        if key in paths:
            raise ValueError('Merge membership is inconsistent; review its audit history')
        paths[key] = path
        group = groups.get(key)
        if group:
            group = {**group, 'members': json.loads(group['members'])}
            nodes[key] = group
            for member in reversed(group['members']):
                edge = db.execute('SELECT 1 FROM decisions WHERE alias=? AND canonical=? AND active=1',
                                  (member['id'], key)).fetchone()
                if not edge:
                    raise ValueError('Merge membership changed; refresh the directory')
                stack.append((member['id'], [*path, key]))
    ids = set(paths)
    profiles = {r['id']: json.loads(r['data']) for r in db.execute('SELECT * FROM profiles') if r['id'] in ids}
    souls = {r['id']: dict(r) for r in db.execute('SELECT * FROM entity_souls') if r['id'] in ids}
    reviews = [dict(r) for r in db.execute('SELECT * FROM entity_integrity') if r['id'] in ids]
    return dict(groups=nodes, paths=paths, profiles=profiles, souls=souls, reviews=reviews)


def member_rows(snapshot, entries, records, links):
    """Use original mentions, before alias projection hides the individual members."""
    from modules.hfl_corpus.entities import entry_hash, explicit_mentions
    from workflows.hfl.entity_store import VERSION
    from workflows.hfl.entity_integrity import isolated_mention
    from urllib.parse import quote
    activity = {key: {} for key in snapshot['paths']}
    for entry in entries:
        cached = records.get(entry['id'], {})
        valid = cached.get('hash') == entry_hash(entry) and cached.get('version') in {VERSION, VERSION + '-explicit'}
        mentions = cached.get('mentions', []) if valid else explicit_mentions(entry)
        targets = set(links.get(entry['id'], []))
        for mention in mentions:
            targets.add(mention['id'])
            targets.add(isolated_mention(entry['id'], mention['id']))
        for key in targets.intersection(activity):
            for target in [key, *snapshot['paths'][key]]:
                activity[target][entry['id']] = dict(id=entry['id'], title=entry['title'], date=entry['date'],
                    source=entry['source'], text=entry['text'],
                    href='/hfl-corpus/entities/entry/' + quote(entry['id'], safe=''))
    result = []
    for key, path in snapshot['paths'].items():
        if not path:
            continue
        original = next(m for m in snapshot['groups'][path[-1]]['members'] if m['id'] == key)
        profile = snapshot['profiles'].get(key) or original.get('profile') or {}
        result.append(dict(id=key, label=profile.get('name', original['label']),
            aliases=profile.get('aliases', []), depth=len(path)-1, group=key in snapshot['groups'],
            path=[snapshot['profiles'].get(p, {}).get('name', snapshot['groups'][p]['name']) for p in path],
            entries=sorted(activity[key].values(), key=lambda e: (e['date'], e['id']), reverse=True)))
    return result


def plan(snapshot, identity, member_id):
    paths = snapshot['paths']
    path = paths.get(member_id)
    if not path:
        raise ValueError('Select a member of this merged entity')
    after = copy.deepcopy(snapshot)
    groups, profiles = after['groups'], after['profiles']
    removed = member_id
    changes, retired = [], []
    # Rebuild only the selected ancestry, from its immediate parent to the root.
    for parent in reversed(path):
        before_members = snapshot['groups'][parent]['members']
        members = groups[parent]['members']
        if removed:
            members[:] = [m for m in members if m['id'] != removed]
        if not members:
            if parent == identity:
                raise ValueError('This would empty the group; use Unmerge instead')
            retired.append(parent)
            removed = parent
            continue
        old = profiles.get(parent, {})
        updated = copy.deepcopy(old)
        for field in ('aliases', 'partial_aliases', 'categories', 'emails', 'phones', 'references'):
            def values(rows):
                vals = {v for m in rows for v in (m.get('profile') or {}).get(field, [])}
                if field == 'aliases':
                    vals.update(m['label'] for m in rows if m['label'] != old.get('name'))
                return vals
            # Keep values contributed by remaining members and later curated additions.
            exclusive = values(before_members) - values(members)
            if field in ('aliases', 'partial_aliases'):
                exclusive = {v for v in exclusive if old.get('alias_sources', {}).get(v) != 'user'}
            updated[field] = [v for v in old.get(field, []) if v not in exclusive]
        for m in before_members:
            if m not in members and (m.get('profile') or {}).get('notes'):
                section = f"### {m['label']}\n{m['profile']['notes']}"
                retained = next((v for v in members if v['id'] == m['id']), None)
                notes = (retained.get('profile') or {}).get('notes', '') if retained else ''
                updated['notes'] = replace_inherited(updated.get('notes', ''), section,
                                                     f"### {m['label']}\n{notes}" if notes else '')
        updated['alias_sources'] = {v: source for v, source in old.get('alias_sources', {}).items()
                                    if v in updated['aliases'] or v in updated['partial_aliases']}
        profiles[parent] = updated
        changes.append(dict(id=parent, before=old, after=updated,
                            before_members=before_members, members=copy.deepcopy(members)))
        if paths[parent]:
            ancestor = groups[paths[parent][-1]]
            for m in ancestor['members']:
                if m['id'] == parent:
                    m['profile'] = updated
        removed = None
    return dict(identity=identity, member_id=member_id, revision=digest(snapshot),
                changes=changes, retired=retired)


def commit(identity, member_id, expected, request_id, fingerprint, actor):
    from workflows.hfl.entity_resolution import invalidate_targets
    with get_store().connection() as db:
        db.execute('BEGIN IMMEDIATE')
        previous = entity_merges.existing_operation(db, request_id, fingerprint)
        if previous:
            return previous
        snapshot = tree(db, identity)
        if digest(snapshot) != expected:
            raise ValueError('Members or profiles changed; review a fresh detach preview')
        change = plan(snapshot, identity, member_id)
        parent = snapshot['paths'][member_id][-1]
        db.execute('UPDATE decisions SET active=0 WHERE alias=? AND canonical=? AND active=1', (member_id, parent))
        for key in change['retired']:
            db.execute('UPDATE entity_merges SET active=0 WHERE id=?', (key,))
            db.execute('UPDATE decisions SET active=0 WHERE alias=? AND active=1', (key,))
        updated_souls = {}
        for item in change['changes']:
            db.execute('UPDATE entity_merges SET members=? WHERE id=?', (json.dumps(item['members']), item['id']))
            db.execute('UPDATE profiles SET data=? WHERE id=?', (json.dumps(item['after']), item['id']))
            # Inherited soul rules can otherwise reassign a detached alias. Preserve
            # edited prose but remove inherited rules from the detached branch.
            soul_row = snapshot['souls'].get(item['id'])
            if soul_row:
                soul = json.loads(soul_row['data'])
                branch = snapshot['paths'][member_id][len(snapshot['paths'][item['id']])+1:] + [member_id]
                prefix = ':'.join(branch) + ':'
                for field in ('identity_rules', 'relationships', 'journal'):
                    soul[field] = [r for r in soul.get(field, []) if not r.get('id', '').startswith(prefix)]
                child = branch[0]
                old_child = snapshot['souls'].get(child)
                if old_child:
                    text = json.loads(old_child['data']).get('markdown', '')
                    label = next(m['label'] for m in item['before_members'] if m['id'] == child)
                    new_text = updated_souls.get(child, {}).get('markdown', '')
                    if text:
                        soul['markdown'] = replace_inherited(soul.get('markdown', ''),
                            f'### {label}\n{text}', f'### {label}\n{new_text}' if new_text else '')
                updated_souls[item['id']] = soul
                db.execute('UPDATE entity_souls SET version=version+1,data=? WHERE id=?', (json.dumps(soul), item['id']))
        # Block only cross-partition pairs; valid retained members remain mergeable.
        entity_matching.block_members(db, [identity, member_id], 'detached')
        affected = [identity, member_id, *snapshot['paths'][member_id]]
        invalidate_targets(db, affected)
        db.execute('INSERT OR IGNORE INTO entity_resolution_jobs(entry_id,revision) SELECT id,hash FROM enrichment')
        member = next(m for m in snapshot['groups'][parent]['members'] if m['id'] == member_id)
        # A mention with no saved profile still needs a stable, visible restored identity.
        if member_id not in snapshot['profiles']:
            profile = member.get('profile') or {'name': member['label']}
            db.execute('INSERT INTO profiles(id,kind,data) VALUES (?,?,?)',
                       (member_id, snapshot['groups'][identity]['kind'], json.dumps(profile)))
        event = entity_merges.record_event(db, identity, 'member-detached', actor, dict(
            name=snapshot['profiles'].get(identity, {}).get('name', snapshot['groups'][identity]['name']),
            members=[member], evidence='Owner detached this member; keep separate from the remaining group.',
            changes=change['changes'], retired=change['retired'], souls_before=snapshot['souls'], souls_after=updated_souls))
        result = dict(entity_id=identity, detached_id=member_id, event_id=event, state='complete', action='detached')
        db.execute('INSERT INTO entity_operations VALUES (?,?,?)', (request_id, fingerprint, json.dumps(result)))
        return result
