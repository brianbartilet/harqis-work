"""Read canonical, permission-filtered intent and activity into the owner fleet."""
from modules.agents.semantics import ENTITY_SEMANTICS
import json
from functools import lru_cache
from urllib.parse import quote, urlencode

STATUS_COLORS = {'open': '#facc15', 'active': '#facc15', 'in_progress': '#facc15',
                 'incomplete': '#f87171', 'done': '#4ade80', 'dismissed': '#94a3b8'}


@lru_cache(maxsize=512)
def description_html(text):
    """Present corpus field records as sections; sanitize all Markdown centrally."""
    import re
    from services.markdown import render_markdown
    text = text or ''
    # Corpus hashtags are metadata, not Markdown heading markers.
    text = re.sub(r'^(\s*Tags:[ \t]*)([^\n]*)$',
                  lambda m: m[1] + m[2].replace('#', r'\#'), text, flags=re.M)
    fields = r'(Source|Machine|Entry ID|Synthesized|Moment|What happened|Why it stayed|Possible use|Tags|References|Event|Share|Question|Answer)'
    text = re.sub(r'^\s*' + fields + r':\s*', lambda m: '\n\n**' + m[1] + '**\n\n', text, flags=re.M)
    return str(render_markdown(text))


def receipt_owner(entry, agents):
    """Read only top-level attribution from the fleet audit's JSON payload."""
    if entry.get('source') != 'agents-activity':
        return None
    from workflows.hfl.dto import HflEntry
    text = entry.get('text', '').strip()
    payload = HflEntry.from_markdown('', text).what_happened or text
    try:
        receipt = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(receipt, dict):
        return None
    if 'agent_id' in receipt:
        return next((a['id'] for a in agents if a['id'] == receipt['agent_id']), None)
    # Legacy receipts predate IDs. Only a unique exact structured name is safe.
    matches = [a['id'] for a in agents if a.get('name') and a['name'] == receipt.get('agent_name')]
    return matches[0] if len(matches) == 1 else None


def extend(nodes, edges, agents, configs, snapshot, entries):
    """Canonical status wins over execution receipts; explicit provenance wins over guesses."""
    known = {a['id'] for a in agents}
    agent_spaces = {a['id']: a.get('workspace_ids', []) for a in agents}

    # Remove prior assignments in one pass instead of rescanning all edges per card.
    canonical_actions = {'action:' + item['id'] for item in snapshot.get('actions', [])}
    canonical_actions.update('idea:' + item['id'] for item in snapshot.get('ideas', []))
    removed = []
    for key in list(edges):
        if key[1] in canonical_actions and key[2] == 'assigned to':
            removed.append((key[0], key[1]))
            del edges[key]
    remaining_pairs = {(e['source'], e['target']) for e in edges.values()}
    for source, target in removed:
        if (source, target) not in remaining_pairs and target in nodes:
            nodes[target]['agent_ids'] = [a for a in nodes[target].get('agent_ids', [])
                                          if a != source.removeprefix('agent:')]

    def link(agent, identity, relation):
        if agent in known:
            if agent not in nodes[identity]['agent_ids']:
                nodes[identity]['agent_ids'].append(agent)
            key = ('agent:' + agent, identity, relation)
            edges[key] = dict(zip(('source', 'target', 'relation'), key))

    for collection, kind in [('actions', 'action'), ('ideas', 'idea')]:
        for item in snapshot.get(collection, []):
            identity = kind + ':' + item['id']
            previous = nodes.get(identity, {})
            nodes[identity] = {**previous, 'id': identity, 'record_id': item['id'], 'kind': kind,
                'label': item['title'], 'summary': item.get('description') or item.get('body') or item.get('expected_outcome', ''),
                'url': '/hfl-corpus/actions?' + urlencode({'edit': item['id'], 'edit_kind': 'actionable' if kind == 'action' else 'idea'}),
                'created': item.get('created_at', ''), 'workspace_ids': item.get('workspace_ids', []),
                'agent_ids': list(previous.get('agent_ids', [])), 'state': item['status'],
                'color': ENTITY_SEMANTICS[kind]['color'],
                'status_color': STATUS_COLORS.get(item['status'], '') if kind == 'action' or item['status'] == 'dismissed' else '',
                'summary_html': description_html(item.get('description') or item.get('body') or item.get('expected_outcome', '')),
                'source': item.get('origin', 'Activity Corpus'), 'record': item}
            if kind == 'action':
                assigned = configs.get('card:' + item['id'], {}).get('agent_id')
                link(assigned, identity, 'assigned to')
            elif item.get('origin') != 'manual':
                link('butler', identity, 'monitors generated idea')
            if kind == 'idea':
                assigned = configs.get('idea:' + item['id'], {}).get('agent_id', '')
                nodes[identity]['assigned_agent_id'] = assigned
                link(assigned, identity, 'assigned to')
            for agent in item.get('agent_ids', []):
                link(agent, identity, 'produced')
            for origin in item.get('origin_idea_ids', []):
                key = ('idea:' + origin, identity, 'promoted to')
                edges[key] = dict(zip(('source', 'target', 'relation'), key))

    for entry in entries:
        source = entry.get('source', '')
        text = entry.get('text', '')
        owner = receipt_owner(entry, agents)
        owners = {owner} if owner else set()
        if source == 'sharing-audit' and 'sharing' in known:
            owners.add('sharing')
        identity = 'entry:' + entry['id']
        nodes[identity] = {'id': identity, 'kind': 'entry', 'label': entry.get('title', 'Agent activity'),
            'summary': text[:5000], 'created': entry.get('date', ''), 'source': source,
            'color': '#77dcf5', 'agent_ids': [], 'corpus_entry': True,
            'workspace_ids': entry.get('workspace_ids') or sorted({space for agent in owners for space in agent_spaces.get(agent, [])}),
            'url': '/hfl-corpus/document/' + quote(entry['path'], safe='/') + '#' + quote(entry.get('anchor', ''))}
        for agent in owners:
            link(agent, identity, 'produced')

    # Connections edited through the shared graph dialogs use the same canonical edges.
    for relation in snapshot.get('links', []):
        source, target = relation['source'], relation['target']
        available = lambda identity: identity in nodes or identity.startswith('agent:') and identity[6:] in known
        if not available(source) or not available(target):
            continue
        key = (source, target, relation['relation'])
        edges[key] = {k: relation[k] for k in ('source', 'target', 'relation', 'direction') if k in relation}
        for agent_node, object_node in ((source, target), (target, source)):
            if agent_node.startswith('agent:') and object_node in nodes and agent_node[6:] in known:
                if agent_node[6:] not in nodes[object_node]['agent_ids']:
                    nodes[object_node]['agent_ids'].append(agent_node[6:])


def add_owner(nodes, edges):
    from modules.profile.store import get_profile_store
    profile = get_profile_store().get()
    identity = 'owner:corpus'
    nodes[identity] = {'id': identity, 'kind': 'owner', 'label': profile.display_name or 'Corpus owner',
        'summary': profile.bio or 'Owner of this activity corpus.', 'color': '#a5b4fc',
        'avatar_url': profile.avatar_data_uri, 'agent_ids': [], 'workspace_ids': [], 'created': ''}
    for node in list(nodes.values()):
        if node['kind'] in {'entry', 'action', 'idea'}:
            key = (node['id'], identity, 'belongs to corpus')
            edges[key] = dict(zip(('source', 'target', 'relation'), key))


def read():
    from config import get_settings
    from modules.hfl_corpus.ideas_api import canonical_snapshot
    from modules.hfl_corpus.ideas_api import permitted_snapshot
    from modules.hfl_corpus.fleet_entry_cache import current_entries
    import os
    entries = current_entries()
    snapshot = canonical_snapshot(include_promoted=True) if get_settings().hfl_corpus_api_url and os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') != '1' else permitted_snapshot(entries, include_promoted=True)
    return snapshot, entries
