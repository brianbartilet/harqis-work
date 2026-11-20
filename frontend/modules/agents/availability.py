"""Availability is separate from ownership, saved activation and work history."""
import socket
from fastapi import HTTPException


def connector(user, provider):
    from modules.integrations import store
    import os
    if provider in {'nod', 'n8n'} and os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') == '1' and os.getenv('HARQIS_' + provider.upper() + '_MOCK') == '1':
        return {'available': True, 'reason': '', 'state': 'connected'}
    data = store.get(user, provider)
    reason = ('Not connected' if data.get('status') == 'Not connected' or not data.get('account_id') and not data.get('site') else
              'Connector disabled' if not data.get('enabled') else
              str(data.get('error') or data.get('status')) if data.get('error') or data.get('status') != 'Connected' else '')
    if not reason and provider in {'codex', 'claude'}:
        from modules.hfl_corpus.action_agents import store as terminals
        target = data.get('host') or socket.gethostname()
        candidates = [h for h in terminals().hosts() if h['host'] == target]
        if not any(r['id'] == provider and r['available'] for h in candidates for r in h['runtimes']):
            reason = next((r.get('reason') for h in candidates for r in h['runtimes'] if r['id'] == provider and r.get('reason')), 'Execution host offline or runtime unavailable')
    return {'available': not reason, 'reason': reason, 'state': 'unavailable' if reason else 'connected'}


def for_agent(user, agent, *, hosts=None, gateways=None):
    from modules.integrations import store
    from modules.agents import connections
    from modules.hfl_corpus.action_agents import store as terminals
    runtime = agent['runtime']
    runtime_ready = False
    reason = ''
    if agent.get('connector_user') and agent['connector_user'] != user:
        reason = 'Agent unavailable'
    elif agent.get('mock'):
        reason = 'Preview agent; execution unavailable'
    elif not agent.get('active', True):
        reason = 'Agent deactivated'
    provider = agent.get('connector_provider') or (runtime if runtime in {'codex', 'claude', 'grokbot', 'n8n', 'nod'} else '')
    if not reason and provider:
        health = connector(user, provider)
        data = store.get(user, provider)
        reason = health['reason']
        if not reason and agent.get('connector_site') and data.get('site') != agent['connector_site'] and not data.get('mock'):
            reason = 'Connected installation changed; reconnect this agent'
        if not reason and agent.get('connector_account') and data.get('account_id') != agent['connector_account']:
            reason = 'Connected account changed; reconnect this agent'
        if not reason and agent.get('remote_available') is False:
            reason = 'Agent is no longer available from its provider'
    if not reason and runtime in {'hermes', 'codex', 'claude'}:
        import os
        gateways = connections.summaries(user) if gateways is None else gateways
        gateway = gateways.get(agent.get('id'), {})
        gateway_ready = runtime == 'hermes' and gateway.get('enabled')
        if runtime == 'hermes' and os.getenv('HARQIS_HERMES_URL'):
            from modules.agents.assistant import preference
            gateway_ready = gateway_ready or agent.get('id') == preference(user)['agent_id']
        hosts = terminals().hosts() if hosts is None else hosts
        target = agent.get('overrides', {}).get('agent_host')
        if runtime in {'codex', 'claude'}:
            data = store.get(user, runtime)
            connected_host = data.get('host') or socket.gethostname()
            if target and target != connected_host:
                reason = 'Selected host does not match the connected installation'
            target = connected_host
        candidates = [h for h in hosts if not target or h['host'] == target]
        ready = [h for h in candidates if any(r['id'] == runtime and r['available'] for r in h['runtimes'])]
        runtime_ready = bool(ready) and (bool(target) or len(ready) == 1 or any(h['host'] == socket.gethostname() for h in ready))
        if not runtime_ready and not gateway_ready:
            reason = next((r.get('reason') for h in candidates for r in h['runtimes'] if r['id'] == runtime and r.get('reason')), 'Execution host offline or runtime unavailable')
    if not reason and not provider and runtime not in {'hermes'}:
        reason = 'Profile only; no verified connection'
    return {'available': not reason, 'selectable': not reason, 'cli_available': not reason and runtime_ready,
            'execution_available': not reason and (runtime == 'hermes' and runtime_ready or runtime == 'nod'), 'reason': reason,
            'state': 'unavailable' if reason else 'available'}


def require(user, agent, operation=None):
    state = for_agent(user, agent)
    if not state['available']:
        raise HTTPException(409, state['reason'])
    if operation and not state.get(operation + '_available'):
        raise HTTPException(409, 'This agent has no available ' + operation + ' runtime.')


def decorate_graph(user, agents, nodes, edges):
    by_id = {a['id']: a for a in agents}
    adjacency = {}
    for edge in edges.values():
        if edge['relation'] not in {'monitors', 'receives output', 'supports result'}:
            adjacency.setdefault(edge['source'], set()).add(edge['target'])
    reachable = set()
    queue = []
    for node in nodes.values():
        if node['kind'] == 'connector':
            from modules.integrations import store
            provider = node.get('source', '')
            state = connector(user, provider)
            saved = store.get(user, provider)
            linked = [by_id[a] for a in node.get('agent_ids', []) if a in by_id and by_id[a].get('connector_provider') == provider]
            if linked and not any(a.get('connector_site') == saved.get('site') and (not a.get('connector_account') or a['connector_account'] == saved.get('account_id')) for a in linked):
                state = {'available': False, 'reason': 'This installation is no longer connected'}
            node.update(available=state['available'], availability_reason=state['reason'])
            if state['available']:
                queue.append(node['id'])
        elif node['kind'] == 'agent':
            state = by_id[node['agent_id']]['availability']
            node.update(available=state['available'], availability_reason=state['reason'])
            if state['available']:
                queue.append(node['id'])
    while queue:
        identity = queue.pop()
        if identity in reachable:
            continue
        node = nodes.get(identity)
        if not node or node.get('available') is False:
            continue
        reachable.add(identity)
        queue.extend(adjacency.get(identity, []))
    for node in nodes.values():
        if node['kind'] in {'agent', 'connector', 'owner'}:
            continue
        owners = [by_id[a] for a in node.get('agent_ids', []) if a in by_id]
        available = node['id'] in reachable or not owners or any(a['availability']['available'] for a in owners)
        node.update(available=available, availability_reason='' if available else 'Linked agents or connections are unavailable')
    for node in nodes.values():
        if node.get('available') is False:
            node['color'] = '#64748b'
