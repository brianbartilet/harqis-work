"""Validation and deterministic copying for reusable planning content."""
import calendar
import copy
import uuid
from datetime import date, timedelta


def workspaces(raw):
    values = raw.get('workspace_ids', [])
    if not isinstance(values, list) or len(values) > 30 or any(not isinstance(v, str) or not 1 <= len(v) <= 100 for v in values):
        raise ValueError('Choose up to 30 workspaces.')
    return list(dict.fromkeys(values))


def recurrence(raw):
    rule = raw.get('recurrence')
    if rule is None:
        return None
    if not isinstance(rule, dict) or set(rule) - {'frequency', 'interval', 'start', 'end'}:
        raise ValueError('Invalid recurrence.')
    if rule.get('frequency') not in {'daily', 'weekly', 'monthly', 'yearly'} or type(rule.get('interval')) is not int or not 1 <= rule['interval'] <= 365:
        raise ValueError('Choose a recurrence frequency and interval from 1 to 365.')
    for key in ('start', 'end'):
        value = rule.get(key, '')
        if not isinstance(value, str) or (key == 'start' and not value):
            raise ValueError('A recurring action needs a starting date.')
        if value and date.fromisoformat(value).isoformat() != value:
            raise ValueError('Recurrence dates must use YYYY-MM-DD.')
    if rule.get('end') and rule['end'] < rule['start']:
        raise ValueError('Recurrence end must not precede its start.')
    return {**rule, 'end': rule.get('end', '')}


def next_occurrence(rule, today):
    """Advance from the original anchor, retaining month-end and leap-day intent."""
    anchor = date.fromisoformat(rule['start'])
    for n in range(1, 120000):
        step = n * rule['interval']
        try:
            if rule['frequency'] in {'daily', 'weekly'}:
                candidate = anchor + timedelta(days=step * (7 if rule['frequency'] == 'weekly' else 1))
            else:
                months = anchor.year * 12 + anchor.month - 1 + step * (12 if rule['frequency'] == 'yearly' else 1)
                year, month = divmod(months, 12)
                candidate = date(year, month + 1, min(anchor.day, calendar.monthrange(year, month + 1)[1]))
        except (ValueError, OverflowError):
            return None
        if rule.get('end') and candidate.isoformat() > rule['end']:
            return None
        if candidate > today:
            return candidate.isoformat()
    return None


def copy_lists(lists, *, reset=False):
    result = copy.deepcopy(lists)
    for checklist in result:
        checklist['id'] = uuid.uuid4().hex
        for item in checklist['items']:
            item['id'] = uuid.uuid4().hex
            if reset:
                item['done'] = False
    return result

def list_entities(snapshot):
    result = list(snapshot.get('lists', []))
    for collection, kind in [('actions', 'actionable'), ('ideas', 'idea')]:
        for owner in snapshot.get(collection, []):
            for checklist in owner.get('checklists', []):
                result.append(dict(id='list:' + kind + ':' + owner['id'] + ':' + checklist['id'], checklist=checklist,
                                   owner_kind=kind, owner_id=owner['id'], version=owner['version'], updated_at=owner.get('updated_at', '')))
    return result


def list_graph(snapshot):
    nodes, edges = [], []
    for item in list_entities(snapshot):
        identity, checklist = item['id'], item['checklist']
        nodes.append(dict(id=identity, object_id=identity, kind='lists', label=checklist['title'], **{k: v for k, v in item.items() if k != 'id'}))
        for task in checklist['items']:
            thought = 'thought:' + uuid.uuid5(uuid.NAMESPACE_URL, identity + ':' + task['id']).hex
            nodes.append(dict(id=thought, kind='thoughts', label=task['text'], body=task['text'], done=task['done'], list_id=identity, item_id=task['id']))
            edges.append(dict(source=identity, target=thought, relation='contains', method='list', evidence=''))
    return nodes, edges
