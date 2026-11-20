"""Butler observes connectors without acquiring their execution authority."""
import time
from modules.agents import service, projection
from modules.integrations import store


def snapshot(user):
    from modules.integrations.service import PROVIDERS
    observations = {r['resource']: r.get('observation', {}) for r in store.links(user, 'oversight')}
    result = []
    for provider, info in PROVIDERS.items():
        data = store.get(user, provider)
        if not data.get('enabled') and provider not in {'codex', 'claude'} and not data.get('account') and not any(a.get('connector_user') == user and a.get('connector_provider', a.get('runtime')) == provider for a in service.store().list()):
            continue
        observation = observations.get(provider, {})
        result.append({'provider': provider, 'name': info['name'], 'status': data.get('status', 'unknown'),
                       'observed_at': observation.get('observed_at', ''),
                       'warnings': observation.get('warnings', ['Execution reporting has not been reconciled yet.']),
                       'reporting': observation.get('reporting', 'unknown')})
    return result


def extend_graph(user, nodes, edge, add):
    for connector in snapshot(user):
        provider = connector['provider']
        existing = [v for v in nodes.values() if v['kind'] == 'connector' and v.get('source') == provider]
        if not existing:
            identity = 'connector:' + provider
            add('butler', identity, 'connector', connector['name'],
                'Butler monitors this connection; execution permissions remain with the provider.', '/applications',
                relation='monitors', source=provider, state=connector['status'], observed_at=connector['observed_at'])
            existing = [nodes[identity]] if identity in nodes else []
        for item in existing:
            edge('agent:butler', item['id'], 'monitors')
            if provider in {'codex', 'claude'}:
                import socket
                for agent in service.store().list():
                    if agent['runtime'] != provider or not projection.inspectable(agent, user):
                        continue
                    host = agent.get('overrides', {}).get('agent_host')
                    if host and host != socket.gethostname():
                        continue
                    if not agent.get('connector_site'):
                        edge('agent:' + agent['id'], item['id'], 'connected through')
    from modules.agents.entities import snapshot as inventory
    for link in inventory(user)['edges']:
        if link['source'] in nodes and link['target'] in nodes:
            edge(link['source'], link['target'], link['relation'])


def reconcile(user):
    """Single durable lease bounds overlaps; provider receipts remain idempotent."""
    db = service.initialize()
    with db.connect() as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS fleet_observation_lease (owner TEXT PRIMARY KEY, expires REAL)')
        connection.execute('BEGIN IMMEDIATE')
        row = connection.execute('SELECT expires FROM fleet_observation_lease WHERE owner=?', (user,)).fetchone()
        if row and row[0] > time.time():
            return {'status': 'busy', 'warnings': []}
        lease = time.time() + 600
        connection.execute('INSERT OR REPLACE INTO fleet_observation_lease VALUES (?,?)', (user, lease))
    outcomes = []
    try:
        agents = [a for a in db.list() if projection.visible(a, user) and not a.get('mock')]
        from modules.integrations.service import PROVIDERS
        for provider in PROVIDERS:
            if not store.get(user, provider).get('enabled'):
                continue
            warnings, supported = [], provider in {'codex', 'claude', 'nod', 'n8n'}
            linked = [a for a in agents if a.get('connector_provider', a.get('runtime')) == provider and a.get('connector_user') == user]
            if supported and not linked:
                warnings.append('Connect an agent in Fleet to collect its execution results.')
            for agent in linked[:10]:
                try:
                    if provider == 'claude':
                        from modules.integrations.claude import refresh
                        warnings.extend(refresh(user, agent['id'])['warnings'])
                    elif provider == 'codex':
                        from modules.integrations.codex import refresh
                        warnings.extend(refresh(user, agent['id'])['warnings'])
                    elif provider == 'nod':
                        from modules.integrations.nod_entities import refresh
                        from modules.integrations.nod import capture
                        warnings.extend(refresh(user, agent['id'])['warnings'])
                        capture(user, agent['id'])
                    elif provider == 'n8n' and not agent.get('n8n_library'):
                        from modules.integrations.n8n_fleet import refresh, capture
                        refresh(user, agent['id'])
                        capture(user, agent['id'])
                except Exception:
                    warnings.append('Provider observation failed; last-known work is retained.')
            if not supported:
                warnings.append('Connector visibility only; execution collection is owned by its existing integration.')
            outcome = {'provider': provider, 'observed_at': store.now(), 'warnings': sorted(set(warnings)),
                       'reporting': 'supported' if supported else 'external'}
            store.link(user, 'oversight', provider, {'observation': outcome})
            outcomes.append(outcome)
        from modules.agents.audit import deliver_pending
        delivery = deliver_pending()
        return {'status': 'complete', 'connectors': outcomes, 'delivery': delivery,
                'warnings': [w for o in outcomes if o['reporting'] == 'supported' for w in o['warnings']]}
    finally:
        with db.connect() as connection:
            connection.execute('DELETE FROM fleet_observation_lease WHERE owner=? AND expires=?', (user, lease))
