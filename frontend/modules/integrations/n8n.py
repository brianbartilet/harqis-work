"""n8n REST workflows and capability-discovered MCP agent catalogue."""
import hashlib
import json
from urllib.parse import urlsplit
import httpx
from fastapi import HTTPException


def site(value):
    if not isinstance(value, str):
        raise HTTPException(422, 'Enter the n8n instance URL.')
    value = value.strip().rstrip('/')
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError:
        raise HTTPException(422, 'Invalid n8n URL.') from None
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path or any(c.isspace() for c in value)
            or '\\' in value or (parsed.scheme == 'http' and parsed.hostname not in {'localhost', '127.0.0.1', '::1'})):
        raise HTTPException(422, 'Use the HTTPS n8n origin, or HTTP localhost for a local instance.')
    return value


def browser_origin(value):
    """Navigation only: this address is never used for authenticated API calls."""
    if not isinstance(value, str):
        raise HTTPException(422, 'Enter a browser URL.')
    value = value.strip().rstrip('/')
    if not value:
        return ''
    try:
        parsed = urlsplit(value)
        parsed.port
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment or '\\' in value or any(c.isspace() for c in value)):
            raise ValueError()
    except ValueError:
        raise HTTPException(422, 'Use an HTTP or HTTPS browser origin without a path or credentials.') from None
    return value


class N8n:
    def __init__(self, credentials):
        self.credentials, self.base = credentials, site(credentials['site'])

    def request(self, method, path, *, params=None, json=None):
        try:
            with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
                response = client.request(method, self.base + '/api/v1' + path,
                    headers={'X-N8N-API-KEY': self.credentials['token']}, params=params, json=json)
            if not response.is_success:
                raise HTTPException(502 if response.status_code >= 500 else response.status_code,
                                    'n8n request failed. Check the connection and API permissions.')
            return response.json()
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, 'n8n unavailable or returned an invalid response.') from None

    def test(self):
        self.request('GET', '/workflows', params={'limit': 1})
        capabilities = self._mcp() if self.credentials.get('mcp_token') else []
        return {'account': self.base, 'account_id': hashlib.sha256(self.base.encode()).hexdigest()[:24],
                'agent_discovery': 'search_agents' in capabilities}

    def _mcp(self, tool=None, arguments=None):
        token = self.credentials.get('mcp_token')
        if not token:
            raise HTTPException(409, 'Add an n8n MCP token to discover first-class agents.')
        headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json, text/event-stream'}
        try:
            with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
                def call(method, params, identity=1):
                    message = {'jsonrpc': '2.0', 'method': method, 'params': params}
                    if identity is not None:
                        message['id'] = identity
                    with client.stream('POST', self.base + '/mcp-server/http', headers=headers, json=message) as response:
                        if not response.is_success:
                            raise HTTPException(502, 'n8n MCP unavailable. Check its token and enabled capabilities.')
                        if response.headers.get('mcp-session-id'):
                            headers['Mcp-Session-Id'] = response.headers['mcp-session-id']
                        if identity is None:
                            return {}
                        if 'text/event-stream' in response.headers.get('content-type', ''):
                            total = 0
                            for line in response.iter_lines():
                                total += len(line)
                                if total > 4 * 1024 * 1024:
                                    raise ValueError('Response too large')
                                if line.startswith('data:'):
                                    data = json.loads(line[5:])
                                    if data.get('id') == identity:
                                        break
                            else:
                                raise ValueError('Missing response')
                        else:
                            body = bytearray()
                            for chunk in response.iter_bytes():
                                body.extend(chunk)
                                if len(body) > 4 * 1024 * 1024:
                                    raise ValueError('Response too large')
                            data = json.loads(body)
                    if data.get('error'):
                        raise HTTPException(502, 'n8n MCP rejected the request. Check capability access.')
                    return data['result']
                initialized = call('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                                   'clientInfo': {'name': 'harqis-fleet', 'version': '1.0'}})
                headers['MCP-Protocol-Version'] = initialized.get('protocolVersion', '2024-11-05')
                call('notifications/initialized', {}, None)
                names = [t['name'] for t in call('tools/list', {}, 2).get('tools', [])]
                if tool is None:
                    return names
                if tool not in names:
                    raise HTTPException(409, 'This n8n instance does not expose ' + tool + '. Enable Agents and MCP on a compatible version.')
                result = call('tools/call', {'name': tool, 'arguments': arguments or {}}, 3)
                if result.get('isError'):
                    raise HTTPException(502, 'n8n could not read the agent catalogue.')
                if 'structuredContent' in result:
                    return result['structuredContent']
                return json.loads(next(c['text'] for c in result.get('content', []) if c.get('type') == 'text'))
        except (httpx.HTTPError, ValueError, KeyError, StopIteration):
            raise HTTPException(502, 'n8n MCP response unavailable or invalid.') from None

    def agents(self, query=''):
        return self._mcp('search_agents', {'limit': 100, 'query': query})

    def agent(self, identity):
        return self._mcp('get_agent', {'agentId': identity})


def refresh_agent(user, identity):
    from modules.integrations.service import connected
    from modules.agents.service import store
    connection, client = connected(user, 'n8n')
    db = store()
    try:
        old = db.get(identity)
    except KeyError:
        raise HTTPException(404, 'Agent unavailable.') from None
    if old.get('connector_user') != user or old.get('connector_site') != connection['site']:
        raise HTTPException(404, 'Agent unavailable.')
    remote = client.agent(old['remote_id'])
    # Deliberately project named capabilities, never credential references or
    # the complete remote configuration into frontend or HFL payloads.
    item = {**old, 'instructions': str(remote.get('config', {}).get('instructions', ''))[:20000],
            'skills': [str(s.get('name') or key)[:300] for key,s in remote.get('skills', {}).items()][:50],
            'triggers': [str(t.get('name') or t.get('id'))[:240] + ' · ' + str(t.get('cronExpression', ''))[:50] for t in remote.get('tasks', [])][:50],
            'tools': [str(t.get('descriptor', {}).get('name') or t.get('id'))[:300] for t in remote.get('customTools', [])][:50],
            'remote_runnable': bool(remote.get('isRunnable'))}
    return {'item': db.save(item, identity=identity, version=old['version'])}


def sync(user, query=''):
    from modules.integrations.service import connected
    from modules.agents.service import defaults, initialize
    connection, client = connected(user, 'n8n')
    from modules.integrations.n8n_fleet import refresh, key
    from workflows.hfl.agent_fleet_store import FleetConflict
    db, imported, warnings = initialize(), [], []
    library_id = 'n8n-library-' + key(user, connection['site'])
    db.save({**defaults('n8n workflow library'), 'runtime': 'n8n', 'classification': 'workflows',
             'description': 'All accessible n8n workflows and their dependencies. Inventory only; not a remote agent.',
             'n8n_library': True, 'remote_id': '', 'remote_name': 'n8n workflow library',
             'connector_user': user, 'connector_site': connection['site'],
             **({'mock': True, 'demo_user': user} if connection.get('mock') else {})}, identity=library_id, seed=True)
    library = refresh(user, library_id)['item']
    try:
        result = client.agents(query)
    except HTTPException as exc:
        result = {'data': []}
        warnings.append('Workflow library synchronized. Agent discovery: ' + str(exc.detail))
    for remote in result.get('data', []):
        if not isinstance(remote.get('id'), str) or not isinstance(remote.get('name'), str):
            continue
        identity = 'n8n-' + hashlib.sha256((user + '\0' + connection['site'] + '\0' + remote['id']).encode()).hexdigest()[:24]
        try:
            old = db.get(identity)
        except KeyError:
            old = None
        item = {**(old or defaults(remote['name'][:120])), 'runtime': 'n8n', 'classification': (old or {}).get('classification', 'workflows'), 'remote_id': remote['id'],
                'connector_user': user, 'connector_site': connection['site'], 'remote_name': remote['name'][:120],
                'published': bool(remote.get('published')), 'available_in_mcp': bool(remote.get('availableInMCP')),
                **({'mock': True, 'demo_user': user} if connection.get('mock') else {})}
        if not old or any(old.get(k) != v for k, v in item.items()):
            item = db.save(item, identity=identity, version=old['version'] if old else None)
        imported.append(item['id'])
        if len(imported) <= 25:
            try:
                refresh(user, item['id'])
            except (HTTPException, FleetConflict):
                warnings.append('Agent imported, but its details need refreshing: ' + item['name'])
    if len(imported) > 25:
        warnings.append('Details refreshed for the first 25 agents. Refresh other agents individually.')
    return {'imported': len(imported), 'workflows': len(library['n8n_snapshot']['workflows']),
            'library_id': library_id, 'agent_ids': imported, 'warnings': warnings, 'bounded': len(result.get('data', [])) == 100,
            'message': 'Up to 100 agents per search. Refine the search to discover more.'}
