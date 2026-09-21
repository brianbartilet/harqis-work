"""Content shared by Ideas and Actionables, independent of their lifecycles."""
import copy
import json
import uuid


def consolidated_description(raw):
    description, body = raw.get('description', ''), raw.get('body', '')
    if not description.strip() or description.strip() == body.strip():
        return body
    return description + ('\n\n' + body if body.strip() else '')


def content_fields(raw):
    result = {}
    for key, limit in [('description', 3000), ('body', 60000)]:
        value = raw.get(key, '')
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError(f'{key} must be text of at most {limit} characters.')
        result[key] = value
    result['body'] = consolidated_description(result)
    result['description'] = ''  # Compatibility input; Markdown is the canonical content.
    if len(result['body']) > 60000:
        raise ValueError('Combined description must be at most 60000 characters.')
    lists = raw.get('checklists', [])
    if not isinstance(lists, list) or len(lists) > 20:
        raise ValueError('Use at most 20 checklists.')
    result['checklists'] = copy.deepcopy(lists)
    identities = set()
    for checklist in result['checklists']:
        if not isinstance(checklist, dict) or set(checklist) - {'id', 'title', 'items', 'cover'}:
            raise ValueError('Invalid checklist.')
        if type(checklist.get('cover', False)) is not bool:
            raise ValueError('Checklist cover must be a boolean.')
        checklist.setdefault('cover', False)
        title = checklist.get('title', '')
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise ValueError('Each checklist needs a title of at most 200 characters.')
        items = checklist.get('items', [])
        if not isinstance(items, list) or len(items) > 200:
            raise ValueError('Use at most 200 items per checklist.')
        checklist['items'] = items
        for value in [checklist, *items]:
            if not isinstance(value, dict):
                raise ValueError('Invalid checklist item.')
            value.setdefault('id', uuid.uuid4().hex)
            identity = value['id']
            if not isinstance(identity, str) or not 1 <= len(identity) <= 100 or identity in identities:
                raise ValueError('Checklist IDs must be unique.')
            identities.add(identity)
        for item in items:
            if set(item) - {'id', 'text', 'done'} or not isinstance(item.get('text'), str) or not item['text'].strip() or len(item['text']) > 2000 or type(item.get('done', False)) is not bool:
                raise ValueError('Checklist items need text and a checkbox value.')
            item.setdefault('done', False)
    return result



def migrate_content(db, table):
    """Add compatible defaults once; retain IDs, versions, and audit history."""
    if table not in {'followups', 'timeline_suggestions', 'idea_edits'}:
        raise ValueError('Unsupported content table.')
    db.execute('CREATE TABLE IF NOT EXISTS object_content_migrations (name TEXT PRIMARY KEY)')
    for version in ('checklist-cover-v1', 'markdown-description-v1'):
        key = table + ':' + version
        if db.execute('SELECT 1 FROM object_content_migrations WHERE name=?', (key,)).fetchone():
            continue
        for row in db.execute(f'SELECT id,payload FROM {table}').fetchall():
            item = json.loads(row['payload'])
            if version == 'checklist-cover-v1':
                item.setdefault('checklists', [])
                for checklist in item['checklists']:
                    checklist.setdefault('cover', False)
            else:
                if table == 'timeline_suggestions':
                    item.setdefault('description', item.get('recommendation', ''))
                item['body'] = consolidated_description(item)
                item['description'] = ''
            db.execute(f'UPDATE {table} SET payload=? WHERE id=? AND payload=?', (json.dumps(item), row['id'], row['payload']))
        db.execute('INSERT OR IGNORE INTO object_content_migrations VALUES (?)', (key,))
