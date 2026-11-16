"""Owner-scoped adapter for Nod self-hosted HTTP API (2026-11-16 contract).

Nod has one ongoing conversation per installation. Never manufacture Fleet sessions,
retry mutations automatically, or forward its credentials to a browser.
"""
import hashlib
import json
import json as jsonlib
import uuid

import httpx
from fastapi import HTTPException
from modules.agents.nod_gateway import NodGateway
from modules.agents import service as fleet
from modules.integrations.n8n_fleet import key


class Nod(NodGateway):
    def __init__(self, credentials):
        super().__init__(url=credentials['site'], key=credentials['token'])

    def request(self, method, path, *, json=None):
        try:
            with self.client() as client, client.stream(method, path, json=json) as response:
                if not response.is_success:
                    detail = {401: 'Nod access token was rejected. Reconnect in Integrations.',
                              403: 'Nod rejected the host or access token.',
                              409: 'Nod conversation changed. Refresh before continuing.',
                              404: 'This Nod server does not support the requested operation.',
                              400: 'Nod rejected this message. Refresh or continue in Nod.',
                              503: 'Nod is not ready. Complete model setup in Nod.'}.get(response.status_code, 'Nod request failed. Refresh to reconcile before retrying.')
                    raise HTTPException(response.status_code if response.status_code < 500 else 502, detail)
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 4 * 1024 * 1024:
                        raise ValueError()
                return jsonlib.loads(body)
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, 'Nod response unavailable. Refresh before retrying; a sent message may already have arrived.') from None

    def test(self):
        self.capabilities()
        state = self.request('GET', '/api/state')
        validate_state(state)
        return {'account': 'Nod · ' + self.url, 'account_id': key(self.url), 'conversation': True}


def validate_state(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get('messages'), list) or not isinstance(raw.get('turns'), list):
        raise HTTPException(502, 'Unsupported Nod conversation response.')
    valid_uuid(raw.get('threadId'))
    return raw


def valid_uuid(value):
    try:
        if not isinstance(value, str):
            raise ValueError()
        return str(uuid.UUID(value))
    except ValueError:
        raise HTTPException(422, 'A valid conversation or message ID is required.') from None


def context(user, identity=None, active=False):
    from modules.integrations.service import connected
    data, client = connected(user, 'nod')
    agent = None
    if identity:
        try:
            agent = fleet.store().get(identity)
        except KeyError:
            raise HTTPException(404, 'Nod agent unavailable.') from None
        if (agent.get('runtime') != 'nod' or agent.get('connector_provider') != 'nod'
                or agent.get('connector_user') != user or agent.get('connector_site') != data['site']):
            raise HTTPException(404, 'Nod agent unavailable.')
        if active and not agent['active']:
            raise HTTPException(409, 'Activate this Fleet agent before sending messages.')
    return data, client, agent


def link(user, raw):
    data, client, _ = context(user)
    client.test()
    profile = fleet.validate({**fleet.defaults('Nod'), **raw.get('profile', {}), 'runtime': 'nod'})
    identity = 'nod-' + key(user, data['site'])
    item = fleet.initialize().save({**profile, 'connector_provider': 'nod', 'connector_user': user,
                                   'connector_site': data['site'], 'remote_id': 'owner',
                                   **({'mock': True, 'demo_user': user} if data.get('mock') else {})}, identity=identity, seed=True)
    from modules.integrations.nod_entities import refresh
    return {'item': item, 'discovery': refresh(user, identity)}


def binding(data):
    # Changing credentials invalidates an open composer even if its URL is unchanged.
    return key(data['site'], data.get('credentials', {}).get('token', 'mock'))


def state(user, identity):
    data, client, agent = context(user, identity)
    raw = validate_state(client.request('GET', '/api/state'))
    # Explicit projection excludes raw configuration, provider keys and verification secrets.
    messages = []
    for row in raw['messages'][-150:]:
        message = {k: row.get(k) for k in ('id', 'role', 'text', 'createdAt', 'turnId')}
        message['text'] = str(row.get('displayText') or row.get('text') or '')[:100000]
        approval = row.get('approval')
        if isinstance(approval, dict):
            message['approval'] = {k: approval.get(k) for k in ('id', 'state', 'title', 'description')}
            # Preserve human-readable approval context without exposing arbitrary tool arguments.
            message['approval']['details'] = str(approval.get('text') or approval.get('summary') or '')[:4000]
            message['approval']['fields'] = [{'label': str(f.get('label', ''))[:100], 'value': str(f.get('value', ''))[:4000]} for f in approval.get('fields', [])[:30]]
            message['approval']['body'] = str(approval.get('body') or '')[:4000]
            message['approval']['body_cut'] = bool(approval.get('bodyCut')) or len(str(approval.get('body') or '')) > 4000
        message['open_in_nod'] = bool(row.get('answerChoices') or row.get('attachments') or row.get('presentation'))
        messages.append(message)
    return {'thread_id': raw['threadId'], 'binding': binding(data), 'url': data['site'], 'mock': bool(data.get('mock')),
            'active': agent['active'], 'ready': bool(raw.get('configuration', {}).get('llmReady')),
            'messages': messages, 'has_earlier': bool(raw.get('hasEarlierMessages')),
            'needs_private_input': bool(raw.get('verificationRequests')),
            'turns': [{k: r.get(k) for k in ('id', 'status', 'source', 'createdAt', 'finishedAt')} for r in raw['turns'][:50]],
            'tasks': [{k: r.get(k) for k in ('id', 'title', 'status')} for r in (raw.get('tasks') or [])[:100]]}


def send(user, identity, raw):
    data, client, _ = context(user, identity, active=True)
    if set(raw) - {'thread_id', 'binding', 'request_id', 'text', 'approval_id', 'message_id', 'approved'}:
        raise HTTPException(422, 'Unsupported Nod message fields.')
    if raw.get('binding') != binding(data):
        raise HTTPException(409, 'Nod connection changed. Reload the conversation.')
    thread_id, request_id = valid_uuid(raw.get('thread_id')), valid_uuid(raw.get('request_id'))
    text = raw.get('text', '')
    if not isinstance(text, str) or not text.strip() or len(text) > 20000:
        raise HTTPException(422, 'Enter a message of up to 20,000 characters.')
    current = validate_state(client.request('GET', '/api/state'))
    if current['threadId'] != thread_id:
        raise HTTPException(409, 'Nod conversation was reset. Reload before sending.')
    payload = {'text': text, 'clientMessageId': request_id, 'threadId': thread_id, 'attachmentIds': []}
    if 'approval_id' in raw:
        approval_id, message_id = valid_uuid(raw['approval_id']), valid_uuid(raw.get('message_id'))
        if type(raw.get('approved')) is not bool:
            raise HTTPException(422, 'Choose Approve or Decline explicitly.')
        payload.update(replyToMessageId=message_id, approvalAnswer={'approvalId': approval_id, 'approved': raw['approved']})
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    request_key = key(user, data['site'], request_id)
    db = fleet.store()
    with db.connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        connection.execute('CREATE TABLE IF NOT EXISTS nod_requests (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, response TEXT NOT NULL DEFAULT \'\')')
        if 'response' not in {r['name'] for r in connection.execute('PRAGMA table_info(nod_requests)')}:
            connection.execute("ALTER TABLE nod_requests ADD COLUMN response TEXT NOT NULL DEFAULT ''")
        prior = connection.execute('SELECT fingerprint,response FROM nod_requests WHERE id=?', (request_key,)).fetchone()
        if prior and prior['fingerprint'] != fingerprint:
            raise HTTPException(409, 'This request ID belongs to a different message.')
        if prior and prior['response']:
            return json.loads(prior['response'])
        arrived = next((m for m in current['messages'] if m.get('id') == request_id), None)
        if prior and arrived:
            return {'threadId': thread_id, 'messageId': request_id, 'turnId': arrived.get('turnId'), 'verificationStatus': None}
        if 'approval_id' in raw and not prior:
            matching = next((m for m in current['messages'] if m.get('id') == message_id and
                             (m.get('approval') or {}).get('id') == approval_id and m['approval'].get('state') == 'pending'), None)
            if not matching:
                raise HTTPException(409, 'This approval is no longer pending. Refresh the conversation.')
            if matching['approval'].get('bodyCut') or len(str(matching['approval'].get('body') or '')) > 4000:
                raise HTTPException(409, 'Review the full approval content in Nod before deciding.')
        connection.execute('INSERT OR IGNORE INTO nod_requests(id,fingerprint) VALUES (?,?)', (request_key, fingerprint))
    result = client.request('POST', '/api/messages', json=payload)
    receipt = {k: result.get(k) for k in ('threadId', 'turnId', 'messageId', 'verificationStatus')}
    with db.connect() as connection:
        connection.execute('UPDATE nod_requests SET response=? WHERE id=?', (json.dumps(receipt), request_key))
    return receipt


def stop(user, identity, raw):
    data, client, _ = context(user, identity, active=True)
    if raw.get('confirmed') is not True or raw.get('binding') != binding(data):
        raise HTTPException(409, 'Confirm stopping work in the shared Nod conversation.')
    current = validate_state(client.request('GET', '/api/state'))
    if raw.get('thread_id') != current['threadId']:
        raise HTTPException(409, 'Nod conversation changed. Reload before stopping.')
    client.request('POST', '/api/thread/stop', json={})
    return {'ok': True}


def capture(user, identity):
    snapshot = state(user, identity)
    ids = []
    for turn in snapshot['turns']:
        if turn['status'] not in {'succeeded', 'failed', 'cancelled'}:
            continue
        event_id = 'nod-turn:' + key(user, snapshot['url'], turn['id'])
        fleet.store().event(event_id, identity, {'kind': 'nod-turn', 'agent_name': 'Nod',
                           'turn_id': turn['id'], 'status': turn['status'], 'source': turn['source'],
                           'started_at': turn['createdAt'], 'stopped_at': turn['finishedAt'],
                           'url': snapshot['url'], 'mock': snapshot['mock']})
        ids.append(event_id)
    from modules.agents.audit import deliver_pending
    result = deliver_pending(ids) if not snapshot['mock'] else {'delivered': 0, 'pending': len(ids)}
    return {**result, 'eligible': len(ids), 'preview': snapshot['mock']}
