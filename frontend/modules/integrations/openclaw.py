"""Host-scoped OpenClaw connector; credentials remain with its Gateway."""
import hashlib
import os
import socket
from pathlib import Path
from fastapi import HTTPException
from modules.agents import entities, service as fleet
from modules.integrations import store
from scripts.agents.hfl.terminal_runtimes import openclaw_health


def installation():
    home = Path(os.environ.get('OPENCLAW_STATE_DIR', str(Path.home() / '.openclaw'))).expanduser().resolve()
    config = os.environ.get('OPENCLAW_CONFIG_PATH', str(home / 'openclaw.json'))
    return 'local:' + hashlib.sha256((socket.gethostname() + '\0' + str(home) + '\0' + config).encode()).hexdigest()[:24]


def credentials(raw):
    if raw.get('transport', 'local') != 'local':
        raise HTTPException(422, 'Connect OpenClaw on the HARQIS server host.')
    return {'transport': 'local', 'installation': installation()}


class OpenClaw:
    def __init__(self, credentials):
        self.credentials = credentials

    def test(self):
        if self.credentials.get('installation') != installation():
            raise HTTPException(409, 'OpenClaw installation changed. Reconnect on this host.')
        try:
            openclaw_health()
        except (OSError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from None
        return {'account': 'OpenClaw · ' + socket.gethostname(), 'account_id': installation(),
                'site': installation(), 'host': socket.gethostname()}


def link(user, raw):
    from modules.integrations.service import connected
    data, client = connected(user, 'openclaw')
    client.test()
    identity = 'openclaw-' + hashlib.sha256((user + '\0' + data['site']).encode()).hexdigest()[:24]
    item = fleet.initialize().save({**fleet.defaults('OpenClaw · ' + data['host']), 'runtime': 'openclaw',
        'connector_provider': 'openclaw', 'connector_user': user, 'connector_site': data['site'],
        'connector_account': data['account_id'], 'remote_id': 'installation'}, identity=identity, seed=True)
    scope = 'openclaw:' + data['site']
    connector = entities.entity('connector', scope, 'installation', data['account'], source='openclaw',
        scope=scope, category='connection', state='connected', url='/applications#agent-integrations',
        summary='Host OpenClaw Gateway connection. Interactive sessions use its native TUI; OpenClaw owns execution and schedules.')
    entities.reconcile(user, scope, 'connection', [connector], [('agent:' + item['id'], connector['id'], 'connected through')])
    return {'item': item, 'discovery': {'counts': {'connectors': 1}, 'warnings': []}}
