"""Local Claude Code identity and bounded skill metadata; never reads auth files."""
import hashlib
import json
import os
import socket
import subprocess
from pathlib import Path

import yaml
from fastapi import HTTPException
from modules.agents import entities, service as fleet
from modules.integrations import store
from scripts.agents.hfl.terminal_runtimes import executable


def home():
    return Path(os.environ.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude'))).expanduser().resolve()


def installation():
    return 'local:' + hashlib.sha256((socket.gethostname() + '\0' + str(home())).encode()).hexdigest()[:24]


def credentials(raw):
    if raw.get('transport', 'local') != 'local':
        raise HTTPException(422, 'Connect Claude on the HARQIS server host.')
    return {'transport': 'local', 'installation': installation()}


def skill_roots():
    return [('user', home() / 'skills'), ('project', fleet.ROOT / '.claude/skills')]


class Claude:
    def __init__(self, credentials):
        self.credentials = credentials

    def test(self):
        if self.credentials.get('installation') != installation():
            raise HTTPException(409, 'Claude belongs to another host. Reconnect on this host.')
        try:
            result = subprocess.run([executable('claude'), 'auth', 'status'], capture_output=True, timeout=20)
            data = json.loads(result.stdout)
            if result.returncode or not isinstance(data, dict) or data.get('loggedIn') is not True:
                raise HTTPException(409, 'Sign in to Claude Code on the HARQIS host, then test again.')
        except (OSError, ValueError, subprocess.TimeoutExpired):
            raise HTTPException(409, 'Claude Code is missing or its authentication could not be checked on this host.') from None
        return {'account': 'Claude · ' + socket.gethostname(), 'account_id': installation(), 'site': installation(),
                'host': socket.gethostname(), 'capabilities': {'skills': True, 'execution': 'existing CLI worker', 'history': 'Fleet sessions only'}}


def link(user, raw):
    from modules.integrations.service import connected
    data, client = connected(user, 'claude')
    client.test()
    identity = raw.get('agent_id')
    if identity:
        old = fleet.store().get(identity)
        if old['runtime'] != 'claude' or old.get('connector_user') not in {None, user}:
            raise HTTPException(404, 'Claude profile unavailable.')
        if old.get('connector_site') and old['connector_site'] != data['site']:
            raise HTTPException(409, 'This profile belongs to another installation.')
        profile = old
    else:
        identity = 'claude-' + hashlib.sha256((user + '\0' + data['site']).encode()).hexdigest()[:24]
        profile = fleet.validate({**fleet.defaults('Claude · ' + socket.gethostname()), **raw.get('profile', {}), 'runtime': 'claude'})
        if raw.get('profile'):
            import uuid
            identity = 'claude-' + uuid.uuid4().hex[:24]
    item = fleet.initialize().save({**profile, 'connector_provider': 'claude', 'connector_user': user,
                                   'connector_site': data['site'], 'remote_id': 'installation'}, identity=identity,
                                  **({'version': profile['version']} if raw.get('agent_id') else {'seed': True}))
    return {'item': item, 'discovery': refresh(user, item['id'])}


def refresh(user, identity):
    from modules.integrations.service import connected
    agent = fleet.store().get(identity)
    if agent.get('connector_user') != user or agent.get('connector_provider') != 'claude':
        raise HTTPException(404, 'Claude profile unavailable.')
    scope = 'claude:' + agent['connector_site']
    try:
        data, client = connected(user, 'claude')
        client.test()
        if data['site'] != agent['connector_site']:
            raise HTTPException(409, 'Reconnect this Claude installation.')
        connector = entities.entity('connector', scope, 'installation', data['account'], source='claude',
            scope=scope, category='connection', state='connected', url='/applications',
            summary='Claude Code on the HARQIS host. Sessions use the configured CLI worker.')
        linked = [a for a in fleet.store().list() if a['runtime'] == 'claude' and a.get('connector_user') == user and a.get('connector_site') == data['site']]
        entities.reconcile(user, scope, 'connection', [connector], [('agent:' + a['id'], connector['id'], 'connected through') for a in linked])
        rows, warnings = [], []
        for category, root in skill_roots():
            files = sorted(root.glob('*/SKILL.md'))
            if len(files) > 500:
                warnings.append('Skill inventory exceeds 500 items; last-known ' + category + ' skills retained.')
                continue
            batch, links = [], []
            for path in files:
                try:
                    with path.open('r', encoding='utf-8') as source:
                        text = source.read(65537)
                    if len(text) > 65536:
                        raise ValueError()
                    meta = yaml.safe_load(text.split('---', 2)[1]) if text.startswith('---') and text.count('---') >= 2 else {}
                    meta = meta if isinstance(meta, dict) else {}
                    label = meta.get('name') if isinstance(meta.get('name'), str) else path.parent.name
                    description = meta.get('description') if isinstance(meta.get('description'), str) else ''
                    row = entities.entity('skill', scope + ':' + category, path.parent.name, label or path.parent.name,
                        source='claude', source_object='skills', scope=scope, category=category + '-skills',
                        summary=description[:1000], state='observed')
                    batch.append(row)
                    links.append((connector['id'], row['id'], 'provides skill'))
                except (OSError, ValueError, yaml.YAMLError):
                    warnings.append('Some skill metadata could not be read; last-known inventory retained.')
            if len(batch) == len(files):
                entities.reconcile(user, scope, category + '-skills', batch, links)
            else:
                entities.observe(user, batch, links)
            rows.extend(batch)
        return {'counts': {'skills': len(rows)}, 'warnings': sorted(set(warnings))}
    except HTTPException:
        for category in ('connection', 'user-skills', 'project-skills'):
            entities.stale(user, scope, category, 'stale')
        raise
