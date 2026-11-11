"""Fleet graph projection; Space filters are organizational, connector ownership is not."""
import json
import os
from starlette.datastructures import QueryParams
from modules.agents import service


def visible(agent, user=None):
    if agent.get('mock'):
        return os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') == '1' and agent.get('demo_user') == user
    if agent.get('connector_user'):
        if user != agent['connector_user']:
            return False
        from modules.integrations.store import get
        connector = get(user, agent.get('connector_provider', 'n8n'))
        return (connector.get('enabled') and connector.get('site') == agent.get('connector_site')
                and (not agent.get('connector_account') or connector.get('account_id') == agent['connector_account']))
    return True


def listing(user=None):
    from modules.hfl_corpus.action_agents import store as terminals
    db = terminals()
    db.expire_sessions()
    sessions = db.sessions()
    runs = db.list(limit=1000)
    assistant_activity = {}
    if user:
        with service.store().connect() as connection:
            rows = [(r['kind'], json.loads(r['payload'])) for r in connection.execute(
                "SELECT kind,payload FROM fleet_assistant WHERE user=? AND kind IN ('conversation','turn')", (user,))]
        owners = {v['id']: v['agent_id'] for kind, v in rows if kind == 'conversation'}
        for kind, value in rows:
            if kind == 'turn' and value['conversation_id'] in owners:
                state = {'completed': 'succeeded', 'submitting': 'queued', 'stopping': 'running',
                         'unknown': 'awaiting_input', 'waiting_for_approval': 'awaiting_input'}.get(value['state'], value['state'])
                assistant_activity.setdefault(owners[value['conversation_id']], []).append((value['created'], state))
    result = []
    for agent in service.initialize().list():
        if not visible(agent, user):
            continue
        activity = [(s['activity'], s['state']) for s in sessions if s['settings'].get('fleet_agent', {}).get('id') == agent['id']]
        activity += [(r['updated_at'], r['state']) for r in runs if r['snapshot'].get('execution_settings', {}).get('fleet_agent', {}).get('id') == agent['id']]
        activity += assistant_activity.get(agent['id'], [])
        state = max(activity)[1] if activity else 'ready'
        if any(s in {'running', 'waiting', 'starting', 'queued'} for _, s in activity):
            state = 'running'
        if agent['runtime'] == 'grokbot' and agent.get('connector_user'):
            from modules.integrations.store import get
            connector = get(user, 'grokbot')
            state = ('Reconnect required' if connector.get('status') == 'Reconnect required' else
                     'Sync delayed' if connector.get('error') else
                     'Unavailable' if not agent.get('remote_available', True) else 'Discovered')
        result.append({**agent, 'classification': agent.get('classification', service.SERVICES.get(agent['runtime'], ('', 'general'))[1]),
                       'state': 'Mock' if agent.get('mock') else state, 'last_activity': max(activity)[0] if activity else ''})
    return result


def nodes(context='', query='', since='', until=''):
    params = QueryParams(context)
    spaces = set(filter(None, params.get('views', params.get('workspace', '')).split(',')))
    # Public/recipient graphs never call this projection. User-scoped connector
    # agents are intentionally excluded from the shared owner board catalogue.
    return [dict(id='agent:' + a['id'], kind='agents', label=a['name'],
                 description=a['description'], href='/agents?agent=' + a['id'],
                 color=a['color'], workspace_ids=a['workspace_ids'], updated_at=a['updated_at'])
            for a in service.store().list() if visible(a) and a['active']
            and (not spaces or spaces.intersection(a['workspace_ids']))
            and (not query or query.casefold() in (a['name'] + ' ' + a['description']).casefold())
            and (not since or a['updated_at'][:10] >= since) and (not until or a['updated_at'][:10] <= until)]


def extend(graph, **filters):
    fleet = nodes(**filters)
    ids = {n['id'] for n in graph['nodes']}
    additions = [n for n in fleet if n['id'] not in ids]
    limit = graph.get('limit', 0)
    graph['total_nodes'] = graph.get('total_nodes', len(graph['nodes'])) + len(additions)
    graph['nodes'].extend(additions if not limit else additions[:max(0, limit-len(graph['nodes']))])
    if fleet:
        types = graph.setdefault('types', [])
        if not any(t.get('id') == 'agents' for t in types):
            types.append({'id': 'agents', 'name': 'Agents', 'color': '#8b5cf6'})
    return graph
