"""Observation-only Codex installation adapter (app-server 0.169 schema).

Threads are tasks, turns are executions, installed plugins are applications.
Only summaries are retained, never prompts, command output or plugin secrets.
"""
import hashlib
import json
import os
import re
import socket
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from modules.agents import entities, service as fleet
from modules.integrations import store
from modules.integrations.codex_transport import CodexRPC


def key(*parts):
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:24]


def installation():
    return 'local:' + key(socket.gethostname(), str(Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex'))).resolve()))


def credentials(raw):
    if raw.get('transport', 'local') != 'local':
        raise HTTPException(422, 'This connector observes the local HARQIS host only.')
    return {'transport': 'local', 'installation': installation()}


def rows(raw, field='data', limit=100):
    result = raw.get(field)
    if not isinstance(result, list) or len(result) > limit or any(not isinstance(v, dict) for v in result):
        raise HTTPException(502, 'Unsupported or oversized Codex inventory.')
    return result


def required(row, field):
    value = row.get(field)
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise HTTPException(502, 'Codex identity unavailable.')
    return value


def summary(value):
    text = str(value or '')[:5000]
    # Defence in depth for common credential formats; raw tool output is excluded.
    text = re.sub(r'(?i)(bearer\s+|(?:api[_-]?key|token|password|secret)\s*[:=]\s*)[^\s,;]+', r'\1[redacted]', text)
    return re.sub(r'\b(?:sk-[\w-]{16,}|github_pat_[\w]+|gh[pousr]_[\w]+)\b', '[redacted]', text)


def timestamp(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return store.now()
    try:
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return store.now()


class Codex:
    def __init__(self, credentials):
        self.credentials = credentials

    def test(self):
        if self.credentials.get('installation') != installation():
            raise HTTPException(409, 'Codex connector belongs to another host. Reconnect on this host.')
        with CodexRPC() as rpc:
            rows(rpc.request('thread/list', {'limit': 1}))
        return {'account': 'Codex · ' + socket.gethostname(), 'account_id': installation(), 'host': socket.gethostname(),
                'site': installation(), 'capabilities': {'tasks': True, 'execution': False,
                'events': False, 'plugins': 'checked during discovery', 'accounts': False}}


def context(user):
    from modules.integrations.service import connected
    data, client = connected(user, 'codex')
    if data['site'] != installation():
        raise HTTPException(409, 'Codex installation changed. Reconnect in Integrations.')
    return data, client


def link(user, raw):
    data, _ = context(user)
    identity = 'codex-' + key(user, data['site'])
    profile = fleet.validate({**fleet.defaults('Codex · ' + socket.gethostname()), **raw.get('profile', {}), 'runtime': 'codex'})
    existing_id = raw.get('agent_id')
    if existing_id:
        try:
            old = fleet.store().get(existing_id)
        except KeyError:
            raise HTTPException(404, 'Codex profile unavailable.') from None
        if old['runtime'] != 'codex' or old.get('connector_user') not in {None, user}:
            raise HTTPException(404, 'Codex profile unavailable.')
        if old.get('connector_site') and old['connector_site'] != data['site']:
            raise HTTPException(409, 'This profile belongs to another installation.')
        identity, profile = existing_id, old
    else:
        matches = [a for a in fleet.store().list() if a.get('connector_user') == user and a.get('connector_site') == data['site'] and a.get('connector_provider') == 'codex']
        if matches:
            identity = matches[0]['id']
        if raw.get('profile'):
            import uuid
            identity = 'codex-' + uuid.uuid4().hex[:24]
    item = fleet.initialize().save({**profile, 'connector_provider': 'codex', 'connector_user': user,
        'connector_site': data['site'], 'remote_id': 'installation'}, identity=identity,
        **({'version': profile['version']} if existing_id else {'seed': True}))
    return {'item': item, 'discovery': refresh(user, identity)}


def checkpoint(user, scope):
    resource = 'observation:' + scope
    return resource, next((r.get('progress', {}) for r in store.links(user, 'codex') if r['resource'] == resource), {})


def refresh(user, identity):
    agent = fleet.store().get(identity)
    if agent.get('connector_user') != user or agent.get('connector_provider') != 'codex':
        raise HTTPException(404, 'Codex agent unavailable.')
    scope = 'codex:' + agent['connector_site']
    warnings, counts = [], {}
    resource, progress = checkpoint(user, scope)
    # Installation history has one stable reporting profile, even when several
    # profiles use this connector. A refresh must never reattribute old receipts.
    observer_id = progress.setdefault('observer_agent_id', identity)
    observer = fleet.store().get(observer_id)
    try:
        data, _ = context(user)
        if agent['connector_site'] != data['site']:
            raise HTTPException(409, 'Reconnect this installation.')
        with CodexRPC() as rpc:
            connector = entities.entity('connector', scope, 'installation', data['account'], source='codex', scope=scope, state='connected',
                summary='Observation only · local saved history · five-minute reconciliation', url='/applications')
            entities.observe(user, [connector], [('agent:'+identity, connector['id'], 'connected through')])
            # A bounded cursor sweep alternates active and archived history.
            page = rpc.request('thread/list', {'limit': 10, 'sortKey': 'updated_at',
                'cursor': progress.get('cursor'), 'archived': progress.get('archived', False)})
            tasks = rows(page, limit=10)
            if progress.get('cursor') or progress.get('archived'):
                recent = rows(rpc.request('thread/list', {'limit': 10, 'sortKey': 'updated_at', 'archived': False}), limit=10)
                tasks = list({required(t, 'id'): t for t in [*tasks, *recent]}.values())
            task_entities, edges = [], []
            for task in tasks:
                tid = required(task, 'id')
                status = task.get('status', {})
                node = entities.entity('task', scope, tid, summary(task.get('name') or ('Codex task · ' + timestamp(task.get('createdAt'))[:10]))[:300],
                    source='codex', scope=scope, category='tasks', state=status.get('type', 'unknown') if isinstance(status, dict) else 'unknown',
                    summary='Saved Codex task; live status may require opening Codex.', url='/agents?agent='+identity)
                task_entities.append(node)
                edges.append((connector['id'], node['id'], 'contains'))
                try:
                    cursor = progress.setdefault('turns', {}).get(tid)
                    turns = rpc.request('thread/turns/list', {'threadId': tid, 'limit': 50, 'sortDirection': 'desc', 'itemsView': 'summary', 'cursor': cursor})
                    executions = rows(turns, limit=50)
                    if cursor:
                        latest = rpc.request('thread/turns/list', {'threadId': tid, 'limit': 10, 'sortDirection': 'desc', 'itemsView': 'summary'})
                        executions += rows(latest, limit=10)
                    for turn in executions:
                        record_turn(user, observer, scope, tid, node, turn)
                    if turns.get('nextCursor'):
                        progress['turns'][tid] = turns['nextCursor']
                    else:
                        progress['turns'].pop(tid, None)
                except HTTPException:
                    warnings.append('Some execution history is unavailable; recorded results were retained.')
            # A page is not a complete inventory: never remove unseen tasks.
            entities.observe(user, task_entities, edges)
            counts['tasks'] = len(task_entities)
            progress['cursor'] = page.get('nextCursor')
            if not progress['cursor']:
                progress['archived'] = not progress.get('archived', False)
            # Continue deep turn histories on subsequent visits without unbounded state.
            progress['turns'] = dict(list(progress.get('turns', {}).items())[-500:])
            try:
                plugins = rpc.request('plugin/list', {'forceRefetch': False, 'marketplaceKinds': ['local']})
                applications, links = [], []
                for market in rows(plugins, 'marketplaces', 100):
                    namespace = scope + ':plugins:' + key(required(market, 'name'), market.get('path'))
                    for plugin in rows(market, 'plugins', 2000):
                        if plugin.get('installed') is not True:
                            continue
                        app = entities.entity('application', namespace, required(plugin, 'id'), required(plugin, 'name'),
                            scope=scope, category='applications', source='codex', state='enabled' if plugin.get('enabled') else 'disabled',
                            summary='Installed Codex plugin · ' + str(plugin.get('localVersion') or plugin.get('version') or 'version unknown'))
                        applications.append(app)
                        links.append((connector['id'], app['id'], 'provides'))
                if plugins.get('marketplaceLoadErrors'):
                    entities.observe(user, applications, links)
                    warnings.append('Plugin inventory is partial; last-known applications were retained.')
                else:
                    entities.reconcile(user, scope, 'applications', applications, links)
                counts['applications'] = len(applications)
            except HTTPException as exc:
                entities.stale(user, scope, 'applications', 'unsupported' if exc.status_code == 422 else 'stale')
                warnings.append('Installed plugin discovery unavailable; last-known applications were retained.')
    except HTTPException:
        for category in ('', 'tasks', 'applications'):
            entities.stale(user, scope, category, 'stale')
        warnings.append('Codex host unavailable; last-known observations were retained.')
    previous = next((r.get('observation', {}) for r in store.links(user, 'codex') if r['resource'] == resource), {})
    result = {'counts': counts, 'warnings': sorted(set(warnings)), 'attempted_at': store.now(),
              'observed_at': store.now() if counts else previous.get('observed_at', ''),
              'continuation_pending': bool(progress.get('cursor') or progress.get('turns')),
              'capabilities': {'execution': False, 'events': False, 'accounts': False}}
    store.link(user, 'codex', resource, {'progress': progress, 'observation': result})
    return result


def record_turn(user, agent, scope, tid, task, turn):
    from modules.agents.ecosystem import record
    turn_id = required(turn, 'id')
    status = turn.get('status')
    if status not in {'completed', 'failed'}:
        return
    messages = [v for v in turn.get('items', []) if isinstance(v, dict) and v.get('type') == 'agentMessage' and v.get('phase') != 'commentary']
    answer = summary(messages[-1].get('text')) if messages else 'Codex execution ' + status + '; no final response was available.'
    source_id = tid + ':' + turn_id
    url = '/agents?agent=' + agent['id']
    date = timestamp(turn.get('completedAt') or turn.get('startedAt'))
    obj = record(user, {'id': source_id, 'source': scope, 'agent_id': agent['id'], 'parent_id': 'butler',
        'kind': 'task', 'label': task['label'][:270] + ' · ' + status, 'summary': answer, 'state': status,
        'created': date, 'url': url, 'workspace_ids': agent.get('workspace_ids', [])})
    entities.observe(user, [], [(task['id'], obj['id'], 'has execution')])
    from modules.agents.ecosystem import safe_url
    evidence = list(dict.fromkeys(url for candidate in re.findall(r'https://[^\s<>\[\]()]+', answer)
                                  if (url := safe_url(candidate)) and '?' not in url))[:10]
    for url in evidence:
        artifact = record(user, {'id': source_id + ':' + key(url), 'source': scope, 'agent_id': agent['id'],
            'parent_id': 'butler', 'kind': 'link', 'label': 'Codex result evidence', 'url': url, 'created': date,
            'workspace_ids': agent.get('workspace_ids', [])})
        entities.observe(user, [], [(obj['id'], artifact['id'], 'returned evidence')])
    fleet.store().event('codex-turn:' + key(user, scope, tid, turn_id), agent['id'],
        {'kind': 'codex-turn', 'owner': user, 'agent_name': agent['name'], 'task_id': tid, 'execution_id': turn_id,
         'status': status, 'summary': answer, 'stopped_at': date, 'url': '/agents?agent=' + agent['id'], 'evidence': evidence})
