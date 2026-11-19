"""Action trigger and scoped Butler delegation client; no provider credentials."""
import json
import os
from urllib.parse import urlsplit

import httpx


def call(path, payload=None, *, delegated=False):
    base = os.environ.get('HFL_AGENT_BRIDGE_URL', '').rstrip('/')
    url = urlsplit(base)
    if url.scheme != 'https' and not (url.scheme == 'http' and url.hostname in {'localhost', '127.0.0.1', '::1'}):
        raise ValueError('Configure HTTPS or a loopback bridge URL.')
    if url.username or url.password or url.query or url.fragment or url.path not in {'', '/'}:
        raise ValueError('Use a bridge origin without credentials or a path.')
    token = os.environ.get('HFL_ACTION_DELEGATION_TOKEN' if delegated else 'HFL_AGENT_BRIDGE_TOKEN', '')
    if not token:
        raise ValueError('No authorized execution capability is available.')
    with httpx.Client(timeout=45, trust_env=False, follow_redirects=False) as client:
        response = client.request('GET' if payload is None else 'POST', base + '/api/hfl-agent/' + path,
                                  headers={'Authorization': 'Bearer ' + token}, json=payload)
        if not response.is_success:
            raise ValueError(response.json().get('detail', 'Action request failed.'))
        return response.json()


def trigger(action_id, request_key):
    if not isinstance(action_id, str) or not action_id.startswith('item-') or not action_id[5:].isalnum():
        raise ValueError('Use a canonical Action ID.')
    return call('actions/' + action_id + '/trigger', {'request_key': request_key})


def delegate(agent_id, prompt, request_key):
    return call(_delegation_path(), {'agent_id': agent_id, 'prompt': prompt, 'request_key': request_key}, delegated=True)


def _delegation_path():
    run = os.environ.get('HFL_ACTION_PARENT_RUN', '')
    if len(run) != 32 or any(c not in '0123456789abcdef' for c in run):
        raise ValueError('Delegation is available only inside a running Butler Action.')
    return 'delegation/' + run


def results():
    return call(_delegation_path(), delegated=True)


if __name__ == '__main__':
    import sys
    raw = json.load(sys.stdin)
    operation = raw.pop('operation', 'results')
    if operation not in {'delegate', 'results'}:
        raise SystemExit('Choose delegate or results.')
    print(json.dumps(delegate(**raw) if operation == 'delegate' else results()))
