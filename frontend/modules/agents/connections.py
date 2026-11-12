"""Owner-scoped gateway connections. Secrets never enter fleet profiles or events."""
import hashlib
import json
import uuid

from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from modules.agents import service
from modules.agents.hermes_gateway import Gateway
from modules.agents.nod_gateway import NodGateway
from modules.integrations.store import cipher
from workflows.hfl.agent_fleet_store import now


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS fleet_connections (
        user TEXT NOT NULL, agent_id TEXT NOT NULL, version INTEGER NOT NULL,
        metadata TEXT NOT NULL, secret TEXT NOT NULL, PRIMARY KEY(user,agent_id))''')


def agent_for(user, identity, *, active=False):
    from modules.agents.projection import visible
    agent = service.store().get(identity)
    if not visible(agent, user) or agent.get('mock'):
        raise HTTPException(404, 'Agent unavailable.')
    if agent['runtime'] not in {'hermes', 'nod'}:
        raise HTTPException(422, 'This service has no gateway adapter.')
    if active and not agent['active']:
        raise HTTPException(409, 'Activate this agent before starting or continuing work.')
    return agent


def read(user, identity, *, private=False):
    agent = agent_for(user, identity)
    with service.store().connect() as db:
        schema(db)
        row = db.execute('SELECT * FROM fleet_connections WHERE user=? AND agent_id=?', (user, identity)).fetchone()
    if not row:
        return {'enabled': False, 'version': 0, 'url': '', 'mode': 'setup' if agent['runtime'] == 'nod' else 'chat', 'provider': agent['runtime'], 'readonly_confirmed': False, 'has_key': False}
    value = {**json.loads(row['metadata']), 'version': row['version'], 'has_key': bool(row['secret'])}
    if private:
        try:
            value['key'] = cipher(user, 'fleet-gateway:' + identity).decrypt(row['secret'].encode()).decode() if row['secret'] else ''
        except InvalidToken:
            raise HTTPException(409, 'Connection encryption key changed. Disconnect and configure the gateway again.') from None
    return value


def prepare(user, raw, identity=None):
    allowed = {'enabled', 'version', 'url', 'key', 'mode', 'readonly_confirmed', 'provider'}
    if not isinstance(raw, dict) or set(raw) - allowed or type(raw.get('enabled')) is not bool:
        raise ValueError('Choose a connection mode and supported connection fields.')
    if type(raw.get('version')) is not int or raw['version'] < 0:
        raise ValueError('Supply the current connection version.')
    provider = agent_for(user, identity)['runtime'] if identity else raw.get('provider', 'hermes')
    if provider not in {'hermes', 'nod'} or raw.get('provider', provider) != provider:
        raise ValueError('Connection provider must match the agent service.')
    current = read(user, identity) if identity else {'version': 0}
    if raw['version'] != current['version']:
        raise HTTPException(409, 'Connection changed. Reopen the editor before saving.')
    if not raw['enabled']:
        return {'enabled': False, 'provider': provider, 'url': '', 'mode': 'setup' if provider == 'nod' else 'chat', 'readonly_confirmed': False, 'capabilities': {}}, ''
    url, key = raw.get('url', ''), raw.get('key', '')
    if not isinstance(url, str) or not 1 <= len(url) <= 2000 or not isinstance(key, str) or len(key) > 4096 or any(c in key for c in '\r\n'):
        raise ValueError('Enter a gateway URL and API key.')
    url = url.strip().rstrip('/')
    mode = raw.get('mode', 'chat')
    confirmed = raw.get('readonly_confirmed', False)
    if mode not in ({'setup'} if provider == 'nod' else {'chat', 'execute'}) or type(confirmed) is not bool:
        raise ValueError('Choose a supported interaction mode; Nod currently supports setup only.')
    if mode == 'chat' and not confirmed:
        raise ValueError('Confirm that the gateway API platform has no tools and no_mcp configured for chat.')
    if not key.strip() and identity and current.get('url') == url:
        key = read(user, identity, private=True).get('key', '')
    if not key.strip():
        raise ValueError('Enter an API key. Changing the address requires a new key.')
    if provider == 'nod':
        gateway = NodGateway(url=url, key=key)
        return {'enabled': True, 'provider': provider, 'url': gateway.url, 'mode': 'setup',
                'readonly_confirmed': False, 'capabilities': gateway.capabilities(), 'tested_at': now()}, key.strip()
    gateway = Gateway(url=url, key=key, tool_policy='no-tools-no-mcp' if confirmed else '')
    capabilities = gateway.capabilities(require_readonly=mode == 'chat')
    return {'enabled': True, 'url': gateway.url, 'mode': mode, 'readonly_confirmed': confirmed,
            'capabilities': capabilities, 'tested_at': now()}, key.strip()


def test(user, raw, identity=None):
    metadata, _ = prepare(user, raw, identity)
    return metadata


def save(user, identity, raw):
    metadata, key = prepare(user, raw, identity)
    encrypted = cipher(user, 'fleet-gateway:' + identity).encrypt(key.encode()).decode() if key else ''
    with service.store().connect() as db:
        schema(db)
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT version FROM fleet_connections WHERE user=? AND agent_id=?', (user, identity)).fetchone()
        version = row['version'] if row else 0
        if version != raw['version']:
            raise HTTPException(409, 'Connection changed while testing. Reopen settings before saving.')
        db.execute('INSERT INTO fleet_connections VALUES (?,?,?,?,?) ON CONFLICT(user,agent_id) DO UPDATE SET version=excluded.version,metadata=excluded.metadata,secret=excluded.secret',
                   (user, identity, version + 1, json.dumps(metadata), encrypted))
        service.store().event('gateway:' + uuid.uuid4().hex, identity,
                              {'kind': 'gateway-configured', 'owner': user, 'enabled': metadata['enabled'], 'mode': metadata['mode']}, db=db)
    return {**metadata, 'version': version + 1, 'has_key': bool(key)}


def gateway_for(user, identity):
    agent = agent_for(user, identity, active=True)
    if agent['runtime'] != 'hermes':
        raise HTTPException(422, 'Nod conversation and task execution are not implemented. Open Nod to interact.')
    value = read(user, identity, private=True)
    if not value['enabled']:
        raise HTTPException(409, 'Configure and test this agent’s gateway in Edit before starting a conversation.')
    gateway = Gateway(url=value['url'], key=value['key'], tool_policy='no-tools-no-mcp' if value['readonly_confirmed'] else '')
    # Mode and configuration generation also belong to the session's identity.
    gateway.binding = hashlib.sha256((gateway.binding + ':' + str(value['version']) + ':' + value['mode']).encode()).hexdigest()
    return gateway, value


def status(user, identity):
    value = read(user, identity)
    result = {**value, 'connected': False}
    if value['enabled']:
        try:
            if agent_for(user, identity)['runtime'] == 'nod':
                secret = read(user, identity, private=True)
                capabilities = NodGateway(url=secret['url'], key=secret['key']).capabilities()
                return {**result, 'connected': True, 'capabilities': capabilities,
                        'detail': 'Server reachable. Chat and task execution remain in Nod.'}
            gateway, _ = gateway_for(user, identity)
            result.update(connected=True, capabilities=gateway.capabilities(require_readonly=value['mode'] == 'chat'))
        except HTTPException as exc:
            result['detail'] = exc.detail
    return result


def summaries(user):
    with service.store().connect() as db:
        schema(db)
        return {row['agent_id']: {key: json.loads(row['metadata']).get(key) for key in ('enabled', 'mode', 'tested_at')}
                for row in db.execute('SELECT agent_id,metadata FROM fleet_connections WHERE user=?', (user,))}
