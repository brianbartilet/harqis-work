"""Experimental, read-only Grok Bot roster adapter. Fixed upstream origins only.

Protocol reference: Nuncio-hq/grokbot-cli auth-* and agents.ts (2026-10-27).
No desktop token extraction, remote Bot mutation or xAI inference credentials.
"""
import base64
import hashlib
import json
import logging
import re
import secrets
import time
import uuid
from contextlib import contextmanager
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException
from modules.integrations import store

PROVIDER = 'grokbot'
ORIGIN = 'https://api2.cursor.sh'
WEBSITE = 'https://cursor.com'
CLIENT_ID = 'KbZUR41cY7W6zRSdpSUJ7I7mLYBKOCmB'
INTERVAL = 300


class _RedactPoll(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        if '/auth/poll?' in message:
            record.msg = re.sub(r'(/auth/poll)\?[^\s\"]+', r'\1?[redacted]', message)
            record.args = ()
        return True


# httpx logs request URLs at INFO; the PKCE verifier must stay server-side.
logging.getLogger('httpx').addFilter(_RedactPoll())


def request(path, *, method='POST', token='', payload=None, params=None, pending=False):
    headers = {'Content-Type': 'application/json', 'Origin': WEBSITE}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    try:
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
            with client.stream(method, ORIGIN + path, headers=headers, json=payload,
                               params=params) as response:
                if pending and response.status_code == 404:
                    return None
                if response.status_code in (401, 403):
                    raise HTTPException(401, 'Grok Bot sign-in was rejected. Reconnect or check your account access.')
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 4 * 1024 * 1024:
                        raise ValueError()
                data = json.loads(body)
                if isinstance(data, dict) and (data.get('error') == 'invalid_grant' or data.get('shouldLogout') is True):
                    raise HTTPException(401, 'Grok Bot sign-in expired. Reconnect your account.')
                if not response.is_success:
                    raise HTTPException(502, 'Grok Bot is unavailable or its experimental interface has changed. Try again later.')
                return data
    except (httpx.HTTPError, ValueError, TypeError):
        raise HTTPException(502, 'Grok Bot returned an invalid response or could not be reached. Your saved roster is unchanged.') from None


def token_pair(raw):
    if not isinstance(raw, dict) or any(not isinstance(raw.get(k), str) or not 1 <= len(raw[k]) <= 20000 for k in ('accessToken', 'refreshToken')):
        raise HTTPException(502, 'Grok Bot did not return a valid sign-in. Try reconnecting.')
    return {k: raw[k] for k in ('accessToken', 'refreshToken')}


def claims(token):
    try:
        part = token.split('.')[1]
        value = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))
        return value if isinstance(value, dict) else {}
    except (ValueError, IndexError, UnicodeError):
        return {}


def account_id(pair):
    # Identity is used only after this exact upstream-issued token passes roster auth.
    sub = claims(pair['accessToken']).get('sub')
    if not isinstance(sub, str) or not 1 <= len(sub) <= 500:
        raise HTTPException(502, 'Grok Bot account identity is unavailable. The connection was not replaced.')
    return hashlib.sha256(sub.encode()).hexdigest()


@contextmanager
def locked(user):
    """Cross-process lease serializes token rotation, login, disable and disconnect."""
    identity = str(uuid.uuid4())
    with store.connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS grokbot_locks(user TEXT PRIMARY KEY, identity TEXT, expires REAL)')
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM grokbot_locks WHERE expires < ?', (time.time(),))
        if db.execute('SELECT 1 FROM grokbot_locks WHERE user=?', (user,)).fetchone():
            raise HTTPException(409, 'Grok Bot connection is busy. Try again shortly.')
        db.execute('INSERT INTO grokbot_locks VALUES (?,?,?)', (user, identity, time.time()+120))
    try:
        yield
    finally:
        with store.connection() as db:
            db.execute('DELETE FROM grokbot_locks WHERE user=? AND identity=?', (user, identity))


def attempts():
    with store.connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS grokbot_login(user TEXT PRIMARY KEY, identity TEXT, expires REAL, payload TEXT)')
        db.execute('DELETE FROM grokbot_login WHERE expires < ?', (time.time(),))


def clear_attempt(user):
    attempts()
    with store.connection() as db:
        db.execute('DELETE FROM grokbot_login WHERE user=?', (user,))


def start_login(user):
    with locked(user):
        attempts()
        identity, verifier = str(uuid.uuid4()), secrets.token_urlsafe(32)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        payload = store.cipher(user, PROVIDER).encrypt(json.dumps({'verifier':verifier, 'next_poll':0}).encode()).decode()
        with store.connection() as db:
            db.execute('INSERT INTO grokbot_login VALUES (?,?,?,?) ON CONFLICT(user) DO UPDATE SET identity=excluded.identity,expires=excluded.expires,payload=excluded.payload',
                       (user, identity, time.time()+600, payload))
        return {'attempt_id':identity, 'url':WEBSITE + '/loginDeepControl?' + urlencode({
            'challenge':challenge, 'uuid':identity, 'mode':'login', 'redirectTarget':'cli'}), 'expires_in':600}


def roster(pair):
    raw = request('/aiserver.v1.GrokBotService/ListGrokBotAgents', token=pair['accessToken'], payload={})
    if not isinstance(raw, dict) or set(raw) - {'agents'} or not isinstance(raw.get('agents', []), list):
        raise HTTPException(502, 'Grok Bot roster format changed. Your saved roster is unchanged.')
    rows = raw.get('agents', [])
    if len(rows) > 2000:
        raise HTTPException(502, 'Grok Bot roster exceeds the supported limit.')
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or row.get('kind') not in {'GROK_BOT_AGENT_KIND_AGENT','GROK_BOT_AGENT_KIND_ROOM'}:
            raise HTTPException(502, 'Grok Bot roster contains an unsupported entry.')
        if row['kind'] == 'GROK_BOT_AGENT_KIND_ROOM':
            continue
        try:
            identity = str(uuid.UUID(row['agentId']))
        except (KeyError, ValueError, TypeError, AttributeError):
            raise HTTPException(502, 'Grok Bot roster contains an invalid identity.') from None
        if identity in seen or any(not isinstance(row.get(k, ''), str) for k in ('name','title','description')):
            raise HTTPException(502, 'Grok Bot roster contains invalid or duplicate entries.')
        seen.add(identity)
        result.append({'id':identity, 'name':(row.get('name') or row.get('title') or 'Unnamed Bot')[:120],
                       'description':row.get('description', '')[:3000]})
    return result


def reconcile(user, account, rows):
    from modules.agents.service import defaults, initialize
    from workflows.hfl.agent_fleet_store import FleetConflict
    db = initialize()
    present = set()
    for remote in rows:
        identity = PROVIDER + '-' + hashlib.sha256((user+'\0'+account+'\0'+remote['id']).encode()).hexdigest()[:24]
        present.add(identity)
        for retry in range(3):
            try:
                old = db.get(identity)
            except KeyError:
                old = None
            item = {**(old or defaults(remote['name'])), 'runtime':PROVIDER, 'connector_provider':PROVIDER,
                    'connector_user':user, 'connector_account':account, 'connector_site':WEBSITE,
                    'remote_id':remote['id'], 'remote_name':remote['name'], 'remote_description':remote['description'],
                    'remote_available':True}
            for key in ('name', 'description'):
                if not old or old[key] == old.get('remote_'+key):
                    item[key] = remote[key]
            try:
                if not old or any(old.get(k) != v for k,v in item.items()):
                    db.save(item, identity=identity, version=old['version'] if old else None)
                break
            except FleetConflict:
                if retry == 2:
                    raise HTTPException(409, 'Fleet changed during sync. Refresh again.') from None
    for old in db.list():
        if (old.get('runtime') == PROVIDER and old.get('connector_user') == user and
                old.get('connector_account') == account and old['id'] not in present and old.get('remote_available', True)):
            try:
                db.save({**old, 'remote_available':False}, identity=old['id'], version=old['version'])
            except FleetConflict:
                raise HTTPException(409, 'Fleet changed during sync. Refresh again.') from None
    return len(rows)


def connect_pair(user, pair, method, attempt=None):
    rows = roster(pair)
    account = account_id(pair)
    count = reconcile(user, account, rows)
    previous = store.get(user, PROVIDER)
    metadata = {'status':'Connected', 'enabled':True, 'account':'Grok Bot account', 'account_id':account,
                'site':WEBSITE, 'auth_method':method, 'expiry':'Automatic refresh', 'last_sync':store.now(),
                'last_attempt':time.time(), 'bot_count':count, 'experimental':True,
                'connected_since':previous.get('connected_since', store.now()) if previous.get('account_id') == account else store.now()}
    if attempt:
        # Commit credentials only if this browser attempt is still current.
        # Cancellation can run while upstream polling/roster requests are in flight.
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            valid = db.execute('SELECT 1 FROM grokbot_login WHERE user=? AND identity=? AND expires>?',
                               (user, attempt, time.time())).fetchone()
            if not valid:
                raise HTTPException(410, 'Sign-in expired or was cancelled. Start again.')
            encrypted = store.cipher(user, PROVIDER).encrypt(json.dumps(pair).encode()).decode()
            db.execute('INSERT INTO connectors VALUES (?,?,?,?) ON CONFLICT(user,provider) DO UPDATE SET credentials=excluded.credentials,metadata=excluded.metadata',
                       (user, PROVIDER, encrypted, json.dumps(metadata)))
            db.execute('DELETE FROM grokbot_login WHERE user=? AND identity=?', (user, attempt))
    else:
        store.save(user, PROVIDER, metadata, pair)
        clear_attempt(user)
    return {'status':'Connected', 'imported':count}


def poll_login(user, identity):
    with locked(user):
        attempts()
        with store.connection() as db:
            row = db.execute('SELECT * FROM grokbot_login WHERE user=? AND identity=?', (user, identity)).fetchone()
        if not row:
            raise HTTPException(410, 'Sign-in expired or was cancelled. Start again.')
        state = json.loads(store.cipher(user, PROVIDER).decrypt(row['payload'].encode()))
        if state['next_poll'] > time.time():
            return {'status':'pending'}
        state['next_poll'] = time.time()+3
        with store.connection() as db:
            db.execute('UPDATE grokbot_login SET payload=? WHERE user=?',
                       (store.cipher(user, PROVIDER).encrypt(json.dumps(state).encode()).decode(), user))
        pair = state.get('pair')
        if not pair:
            raw = request('/auth/poll', method='GET', params={'uuid':identity,'verifier':state['verifier']}, pending=True)
            if raw is None:
                return {'status':'pending'}
            pair = token_pair(raw)
            # Upstream poll may be one-shot; retain tokens for a safe roster retry.
            state['pair'] = pair
            with store.connection() as db:
                db.execute('UPDATE grokbot_login SET payload=? WHERE user=?',
                           (store.cipher(user, PROVIDER).encrypt(json.dumps(state).encode()).decode(), user))
        return connect_pair(user, pair, 'Browser sign-in', identity)


def connect_key(user, key):
    if not isinstance(key, str) or not 1 <= len(key.strip()) <= 4096 or any(ord(c)<32 for c in key):
        raise HTTPException(422, 'Enter a Cursor user API key, not an xAI inference key.')
    with locked(user):
        pair = token_pair(request('/auth/exchange_user_api_key', token=key.strip(), payload={}))
        return connect_pair(user, pair, 'Cursor API key exchange')


def refreshed(pair):
    exp = claims(pair['accessToken']).get('exp', 0)
    if isinstance(exp, (int, float)) and exp > time.time()+300:
        return pair
    raw = request('/oauth/token', payload={'client_id':CLIENT_ID, 'grant_type':'refresh_token', 'refresh_token':pair['refreshToken']})
    if not isinstance(raw, dict):
        raise HTTPException(502, 'Grok Bot returned an invalid token refresh.')
    return token_pair({'accessToken':raw.get('access_token'), 'refreshToken':raw.get('refresh_token') or pair['refreshToken']})


def sync(user, if_stale=False):
    with locked(user):
        data = store.get(user, PROVIDER, private=True)
        if not data.get('enabled') or not data.get('credentials'):
            return {'status':'disabled', 'imported':0}
        if if_stale and time.time()-data.get('last_attempt', 0) < INTERVAL:
            return {'status':'cached', 'imported':data.get('bot_count', 0), 'error':data.get('error', '')}
        if data['status'] == 'Reconnect required':
            return {'status':'Reconnect required', 'error':data.get('error', '')}
        data['last_attempt'] = time.time()
        store.save(user, PROVIDER, data)
        try:
            pair = refreshed(data['credentials'])
            # Persist rotation before requesting roster, including on transient failure.
            store.save(user, PROVIDER, data, pair)
            rows = roster(pair)
            if account_id(pair) != data['account_id']:
                raise HTTPException(401, 'Grok Bot account changed. Reconnect explicitly.')
            count = reconcile(user, data['account_id'], rows)
            data.update(status='Connected', last_sync=store.now(), bot_count=count)
            data.pop('error', None)
            store.save(user, PROVIDER, data)
            return {'status':'Connected', 'imported':count}
        except HTTPException as exc:
            data['error'] = exc.detail
            if exc.status_code == 401:
                data['status'] = 'Reconnect required'
            store.save(user, PROVIDER, data)
            raise


def toggle(user, enabled):
    if type(enabled) is not bool:
        raise HTTPException(422, 'Expected an enabled boolean.')
    with locked(user):
        data = store.get(user, PROVIDER, private=True)
        if enabled and not data.get('credentials'):
            raise HTTPException(409, 'Connect Grok Bot first.')
        data['enabled'] = enabled
        store.save(user, PROVIDER, data)
    return sync(user) if enabled else {'status':'disabled'}


def cancel(user, identity):
    attempts()
    with store.connection() as db:
        db.execute('DELETE FROM grokbot_login WHERE user=? AND identity=?', (user, identity))
    return {'status':'cancelled'}


def disconnect(user):
    with locked(user):
        clear_attempt(user)
        return store.save(user, PROVIDER, {'status':'Not connected', 'enabled':False}, {})
