"""Owner-scoped agent/output graph. Projections read recorded work; never dispatch it."""
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, quote

from fastapi import HTTPException
from modules.agents import service, projection
from modules.agents.semantics import ENTITY_SEMANTICS
from workflows.hfl.agent_fleet_store import now

KINDS = {'configuration': '#94a3b8', 'workflow': '#60a5fa', 'trigger': '#c4b5fd', 'application': '#fbbf24',
         'action': ENTITY_SEMANTICS['action']['color'], 'idea': ENTITY_SEMANTICS['idea']['color'], 'entry': '#77dcf5', 'file': '#70edbd',
         'link': '#93c5fd', 'feed': '#5eead4', 'hud': '#e9c96c', 'task': '#a7f3d0', 'subagent': '#deafff'}


def safe_url(value):
    if not isinstance(value, str) or len(value) > 2000 or any(c in value for c in ('\\', '\n', '\r', '\x00')):
        return ''
    parsed = urlsplit(value)
    if value.startswith('/') and not value.startswith('//'):
        return value
    if parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password:
        return value
    return ''


def record(user, raw):
    """Adapter contract: deduplicate a provider object by stable owner/source/id.

    Providers report bounded metadata and canonical links, never arbitrary files
    or secrets. This owner endpoint does not grant an agent execution authority.
    """
    allowed = {'id', 'agent_id', 'parent_id', 'kind', 'label', 'summary', 'url', 'created', 'state', 'source', 'workspace_ids', 'delegation_id'}
    if set(raw) - allowed or not {'id', 'agent_id', 'kind', 'label', 'source'} <= raw.keys():
        raise ValueError('Supply a stable source identity, agent, kind and label.')
    if raw['kind'] not in KINDS:
        raise ValueError('Unsupported connected object type.')
    for field in ('id', 'agent_id', 'parent_id', 'label', 'source', 'state', 'delegation_id'):
        if not isinstance(raw.get(field, ''), str) or len(raw.get(field, '')) > 300:
            raise ValueError('Invalid ' + field + '.')
    if not raw['id'].strip() or not raw['source'].strip() or not raw['label'].strip():
        raise ValueError('Object identity, source and label cannot be empty.')
    agents = {a['id'] for a in projection.listing(user)}
    if raw['agent_id'] not in agents or raw.get('parent_id') and raw['parent_id'] not in agents:
        raise HTTPException(404, 'Agent unavailable.')
    created = raw.get('created', now())
    if not isinstance(created, str) or len(created) > 60:
        raise ValueError('Use an ISO timestamp with a timezone.')
    stamp = datetime.fromisoformat(created.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Use a timestamp with a timezone.')
    spaces = raw.get('workspace_ids', [])
    if not isinstance(spaces, list) or len(spaces) > 50 or any(not isinstance(v, str) or len(v) > 100 for v in spaces):
        raise ValueError('Invalid Spaces.')
    summary = raw.get('summary', '')
    if not isinstance(summary, str) or len(summary) > 5000:
        raise ValueError('Keep the summary within 5,000 characters.')
    identity = hashlib.sha256(json.dumps([raw['source'], raw['id']]).encode()).hexdigest()
    value = {**raw, 'id': 'object:' + identity, 'created': stamp.astimezone(timezone.utc).isoformat(),
             'url': safe_url(raw.get('url', '')), 'workspace_ids': spaces, 'summary': summary}
    with service.store().connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if raw.get('delegation_id'):
            delegation = db.execute('SELECT payload FROM fleet_objects WHERE user=? AND id=?', (user, raw['delegation_id'])).fetchone()
            if not delegation:
                raise HTTPException(404, 'Temporary subagent unavailable.')
            delegation = json.loads(delegation[0])
            if delegation['kind'] != 'subagent' or delegation['agent_id'] != raw['agent_id']:
                raise ValueError('Subagent artifacts must return to the same parent agent.')
        previous = db.execute('SELECT payload FROM fleet_objects WHERE user=? AND id=?', (user, value['id'])).fetchone()
        if previous:
            old = json.loads(previous[0])
            if any(old.get(k) != value.get(k) for k in ('agent_id', 'parent_id', 'kind')):
                raise HTTPException(409, 'An observed object cannot change its producer or parent.')
        db.execute('INSERT INTO fleet_objects VALUES (?,?,?) ON CONFLICT(user,id) DO UPDATE SET payload=excluded.payload',
                   (user, value['id'], json.dumps(value)))
    return value


def graph(user):
    from modules.hfl_corpus.action_agents import store as terminals
    agents = projection.listing(user)
    by_id = {a['id']: a for a in agents}
    nodes, edges, errors = {}, {}, []

    def edge(source, target, relation):
        edges[(source, target, relation)] = {'source': source, 'target': target, 'relation': relation}

    def add(agent_id, identity, kind, label, summary='', url='', created='', relation='produced', **extra):
        if agent_id not in by_id:
            return
        nodes.setdefault(identity, dict(id=identity, kind=kind, label=str(label)[:300], summary=str(summary)[:5000],
                         url=safe_url(url), created=created, color=KINDS.get(kind, '#94a3b8'),
                         workspace_ids=by_id[agent_id]['workspace_ids'], agent_ids=[], **extra))
        if agent_id not in nodes[identity]['agent_ids']:
            nodes[identity]['agent_ids'].append(agent_id)
        edge('agent:' + agent_id, identity, relation)

    catalog = service.catalogue()
    if 'sharing' in by_id and 'butler' in by_id:
        edge('agent:butler', 'agent:sharing', 'delegates to')
    labels = {v['id']: v['name'] for v in catalog['skills'] + catalog['workflows']}
    for agent in agents:
        aid = agent['id']
        for group, kind in [('skills', 'configuration'), ('tools', 'configuration'), ('workflows', 'workflow'), ('triggers', 'trigger')]:
            for value in agent[group]:
                add(aid, group + ':' + value, kind, labels.get(value, value), relation='configured',
                    url='/workflows' if kind in {'workflow', 'trigger'} else '')
        for child in agent['subagents']:
            if child in by_id:
                edge('agent:' + aid, 'agent:' + child, 'delegates to')

    from modules.integrations.n8n_fleet import extend_graph
    extend_graph(agents, nodes, edge, add)
    for agent in agents:
        if agent.get('connector_provider') != 'nod':
            continue
        for event in service.store().events(agent['id']):
            payload = event['payload']
            if payload.get('kind') != 'nod-turn':
                continue
            task_id = event['id'] + ':task'
            add(agent['id'], task_id, 'task', 'Nod · ' + payload['status'],
                'Nod conversation turn · ' + str(payload.get('source', '')), payload['url'],
                payload.get('started_at') or event['created'], relation='observes', state=payload['status'], mock=payload.get('mock', False))
            add(agent['id'], event['id'], 'entry', 'Nod activity receipt',
                'Preview receipt' if payload.get('mock') else 'Recorded in Activity Corpus' if event['delivered'] else 'Queued for Activity Corpus',
                payload['url'], event['created'], state='preview' if payload.get('mock') else 'recorded' if event['delivered'] else 'pending', mock=payload.get('mock', False))
            edge(task_id, event['id'], 'captured as')
    db = terminals()
    runs = db.list(limit=201)
    for run in runs[:200]:
        agent_id = run['snapshot'].get('execution_settings', {}).get('fleet_agent', {}).get('id')
        if agent_id not in by_id:
            continue
        source = run['source_key'].partition(':')[2]
        url = '/hfl-corpus/actions?integration_agent=' + quote(source)
        result = run.get('result') or {}
        add(agent_id, 'action:' + source, 'action', run['snapshot'].get('source', {}).get('title', 'Agent action'),
            result.get('summary', ''), url, run['updated_at'], state=run['state'], source='Action bridge',
            execution={'id': run['id'], 'agent_id': agent_id, 'state': run['state'],
                       'updated_at': run['updated_at'], 'url': url})
        for artifact in db.artifacts(run['id']):
            add(agent_id, 'artifact:' + run['id'] + ':' + artifact['digest'], 'file', artifact['name'],
                str(artifact['size']) + ' bytes · open the action to download', url, run['updated_at'], source='Action bridge')
            edge('action:' + source, 'artifact:' + run['id'] + ':' + artifact['digest'], 'returned artifact')
        for i, link in enumerate(result.get('evidence', [])[:20]):
            if isinstance(link, str) and safe_url(link):
                add(agent_id, 'evidence:' + run['id'] + ':' + str(i), 'link', 'Evidence link', '', link, run['updated_at'], source='Action bridge')
                edge('action:' + source, 'evidence:' + run['id'] + ':' + str(i), 'supports result')
    with service.store().connect() as connection:
        objects = [json.loads(r[0]) for r in connection.execute('SELECT payload FROM fleet_objects WHERE user=? ORDER BY rowid DESC LIMIT 501', (user,))]
        receipts = [json.loads(r[0]) for r in connection.execute("SELECT payload FROM fleet_assistant WHERE user=? AND kind='proposal'", (user,))]
    for item in receipts:
        if item.get('state') == 'verified':
            add(item['agent_id'], 'action:' + item['action_id'], 'action', item['payload']['title'], item['payload']['expected_outcome'],
                item['url'], item.get('verified_at', ''), source='Approved assistant action', state='verified')
    for item in objects[:500]:
        if item.get('mock') and os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') != '1':
            continue
        extra = {k: item[k] for k in ('state', 'source', 'mock', 'temporary') if k in item}
        add(item['agent_id'], item['id'], item['kind'], item['label'], item.get('summary', ''),
            item.get('url', ''), item.get('created', ''), **extra)
        if item['id'] not in nodes:
            continue
        if item.get('workspace_ids'):
            nodes[item['id']]['workspace_ids'] = item['workspace_ids']
        if item.get('parent_id') in by_id:
            parent = item['parent_id']
            if parent not in nodes[item['id']]['agent_ids']:
                nodes[item['id']]['agent_ids'].append(parent)
            edge('agent:' + parent, item['id'], 'receives output')
        if item.get('delegation_id'):
            edge(item['delegation_id'], item['id'], 'returns artifact')
    feed_items = []
    # Butler is the monitor, not a fabricated author of deterministic results.
    try:
        from modules.second_brain.service import get_second_brain_store
        feed_items = get_second_brain_store().feed_snapshot(client='web', limit=81)['items']
        for item in feed_items[:80]:
            add('butler', 'brain:' + item.get('logical_key', item.get('id', '')), 'feed', item.get('title', 'Second Brain update'),
                item.get('summary', ''), '/second-brain/feed', item.get('generated_at', ''), relation='monitors', source='Second Brain')
    except Exception:
        errors.append('Second Brain feed unavailable. Other recorded outputs remain visible.')
    try:
        from modules.second_brain.hud import inventory
        for item in inventory():
            add('butler', 'hud:' + item['operation_id'], 'hud', item['label'], item.get('source_task', ''),
                '/second-brain/hud', relation='monitors', source='HUD catalogue')
    except Exception:
        errors.append('Second Brain catalogue unavailable. Other recorded outputs remain visible.')
    corpus_available = True
    try:
        from modules.agents import corpus_projection
        snapshot, entries = corpus_projection.read()
        corpus_projection.extend(nodes, edges, agents, db.configs(), snapshot, entries)
    except Exception:
        corpus_available = False
        errors.append('Corpus actions, ideas or activity could not refresh. Retry to load their current state.')
    for agent in agents:
        related = [n for n in nodes.values() if agent['id'] in n['agent_ids']]
        # Activity counters are metadata; the graph sizes nodes from visible edges.
        configured = len(set(agent['workflows'] + agent['triggers']))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        recent = sum(n['kind'] not in {'configuration', 'hud'} and (n.get('created', '') >= cutoff or n['kind'] in {'workflow', 'trigger'}) for n in related)
        nodes['agent:' + agent['id']] = {'id': 'agent:' + agent['id'], 'kind': 'agent', 'label': agent['name'],
            'agent_id': agent['id'], 'agent_ids': [agent['id']], 'summary': agent['description'], 'color': agent['color'] if agent['active'] else '#94a3b8',
            'workspace_ids': agent['workspace_ids'], 'created': agent['created_at'],
            'activity_count': recent, 'configured_count': configured, 'state': agent['state'], 'mock': agent.get('mock', False)}
    from modules.agents.corpus_projection import add_owner
    add_owner(nodes, edges)
    return {'agents': agents, 'nodes': list(nodes.values()), 'edges': [e for e in edges.values() if e['source'] in nodes and e['target'] in nodes],
            'types': [{'id': k, 'name': k.replace('_', ' ').title(), 'color': v} for k, v in KINDS.items()],
            'warnings': errors, 'corpus_available': corpus_available,
            'execution_limited': len(runs) > 200,
            'coverage': {'runs': {'returned':min(len(runs),200),'limit':200,'has_more':len(runs)>200}, 'observations':{'returned':min(len(objects),500),'limit':500,'has_more':len(objects)>500}, 'context_feed':{'returned':min(len(feed_items),80),'limit':80,'has_more':len(feed_items)>80}, 'corpus':{'available':corpus_available,'total':None}},
            'demo_available': os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') == '1', 'generated_at': now()}


def seed_demo(user):
    if os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') != '1':
        raise HTTPException(403, 'Mock data is available only in the isolated local preview.')
    db = service.initialize()
    prefix = 'demo-' + hashlib.sha256(user.encode()).hexdigest()[:10] + '-'
    definitions = [('ada', 'Ada · Senior developer', 'codex', '#67e8f9'),
                   ('leo', 'Leo · Junior developer', 'claude', '#deafff'),
                   ('sage', 'Sage · Research partner', 'chatgpt', '#70edbd'),
                   ('atlas', 'Atlas · Operations', 'n8n', '#fb8ca6'),
                   ('nova', 'Nova · Market watch', 'grokbot', '#a7f3d0'),
                   ('iris', 'Iris · Personal researcher', 'hermes', '#93c5fd')]
    for key, name, runtime, color in definitions:
        db.save({**service.defaults(name), 'runtime': runtime, 'classification': service.SERVICES[runtime][1],
                 'description': 'Mock agent for local interaction testing. No remote account or execution is connected.',
                 'color': color, 'mock': True, 'demo_user': user}, identity=prefix + key, seed=True)
    samples = [
        ('butler', 'hud', 'Morning command centre', 'Second Brain HUD · calendar, priorities and health', 'mac-hermes', ''),
        ('butler', 'feed', 'Telegram morning briefing', 'Simulated delivery from the Mac Hermes schedule', 'telegram', ''),
        ('butler', 'task', 'Calendar collection completed', 'Celery finished collecting 12 calendar events', 'celery', ''),
        ('butler', 'entry', 'Daily activity digest', 'A recorded activity entry with decisions and follow-ups', 'hfl', ''),
        ('demo-ada', 'action', 'Ship the agent workspace', 'Completed implementation with tests and review artifacts', 'codex', ''),
        ('demo-ada', 'file', 'Implementation review.md', 'Mock file artifact returned with the completed task', 'codex', ''),
        ('demo-ada', 'subagent', 'Milo · Test specialist', 'Temporary subagent · tests complete · artifacts returned to Ada', 'codex', 'butler'),
        ('demo-ada', 'file', 'Milo regression report', 'Returned by temporary test specialist to Ada and HARQIS Butler', 'codex', 'butler'),
        ('demo-leo', 'action', 'Fix the mobile toolbar', 'Work in progress: review responsive spacing', 'claude', 'demo-ada'),
        ('demo-leo', 'configuration', 'Junior developer model profile', 'Conservative changes, senior review required', 'claude', ''),
        ('demo-sage', 'idea', 'A weekly learning digest', 'Connect activity entries to a concise weekly reflection', 'chatgpt', ''),
        ('demo-sage', 'link', 'Research reference', 'A source link attached to the research output', 'chatgpt', ''),
        ('demo-atlas', 'workflow', 'Invoice reconciliation', 'Three connected app steps with deterministic retries', 'n8n', ''),
        ('demo-atlas', 'trigger', 'Weekdays at 09:00', 'Simulated schedule; no scheduler was changed', 'n8n', ''),
        ('demo-atlas', 'task', 'Reconciled 24 invoices', 'Completed unit of work from the invoice workflow', 'n8n', 'butler'),
        ('demo-nova', 'workflow', 'Watch product announcements', 'Grok Bot workflow discovery example', 'grokbot', ''),
        ('demo-nova', 'feed', 'Three relevant announcements', 'A feed output with links ready for review', 'grokbot', 'butler'),
        ('demo-iris', 'trigger', 'Mac daily research', 'Machine-local Hermes schedule example', 'hermes', ''),
        ('demo-iris', 'subagent', 'Scout · Source verification', 'Temporary subagent currently verifying citations', 'hermes', 'butler'),
        ('demo-iris', 'entry', 'Research notes captured', 'Evidence reported to the parent research agent', 'hermes', 'butler')]
    with db.connect() as connection:
        for index, (agent, kind, label, summary, source, parent) in enumerate(samples):
            agent = agent.replace('demo-', prefix)
            parent = parent.replace('demo-', prefix)
            identity = 'demo-object:' + str(index)
            value = {'id': identity, 'agent_id': agent, 'kind': kind, 'label': label, 'summary': summary,
                     'source': source, 'parent_id': parent, 'mock': True, 'temporary': kind == 'subagent',
                     'state': 'running' if index in {8, 18} else 'completed', 'url': '', 'workspace_ids': [],
                     'created': (datetime.now(timezone.utc) - timedelta(hours=index * 9)).isoformat()}
            if index == 7:
                value['delegation_id'] = 'demo-object:6'
            connection.execute('INSERT OR IGNORE INTO fleet_objects VALUES (?,?,?)', (user, identity, json.dumps(value)))
    return {'agents': len(definitions), 'objects': len(samples)}
