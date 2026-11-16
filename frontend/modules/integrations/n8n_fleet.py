"""Owner-scoped n8n projections. Never persist node parameters or execution data."""
import hashlib
import json
import os
import re
from urllib.parse import quote

from fastapi import HTTPException
from modules.agents import service
from modules.integrations.service import connected
from workflows.hfl.agent_fleet_store import now, FleetConflict


def key(*parts):
    return hashlib.sha256('\0'.join(str(p) for p in parts).encode()).hexdigest()[:24]


def context(user, identity=None):
    connection, client = connected(user, 'n8n')
    item = None
    if identity:
        try:
            item = service.store().get(identity)
        except KeyError:
            raise HTTPException(404, 'Agent unavailable.') from None
        if (item.get('runtime') != 'n8n' or item.get('connector_user') != user
                or item.get('connector_site') != connection['site']):
            raise HTTPException(404, 'Agent unavailable.')
    return connection, client, item


def workflows(client):
    result, cursor, seen = [], '', set()
    for _ in range(10):
        page = client.request('GET', '/workflows', params={'limit': 100, **({'cursor': cursor} if cursor else {})})
        result.extend(page.get('data', []))
        cursor = page.get('nextCursor') or ''
        if not cursor:
            return result, False
        if cursor in seen:
            break
        seen.add(cursor)
    return result, True


def workflow_view(raw, origin):
    apps, schedules, children = {}, [], []
    for node in raw.get('nodes', []):
        kind = str(node.get('type', ''))[:200]
        slug = kind.rsplit('.', 1)[-1]
        # Node type is evidence of a dependency, not evidence of authenticated access.
        label = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', slug).strip().title()
        internal = slug in {'code', 'set', 'if', 'switch', 'merge', 'noOp', 'manualTrigger', 'scheduleTrigger', 'cron', 'executeWorkflow', 'executeWorkflowTrigger', 'webhook', 'respondToWebhook', 'wait', 'httpRequest'}
        apps.setdefault(kind, {'id': kind, 'name': label, 'nodes': 0, 'kind': 'configuration' if internal else 'application'})['nodes'] += 1
        params = node.get('parameters') or {}
        if slug in {'scheduleTrigger', 'cron'}:
            schedules.append({'id': str(node.get('id', ''))[:200], 'name': str(node.get('name', 'Schedule'))[:200],
                              'enabled': bool(raw.get('active')) and not node.get('disabled', False),
                              'timezone': str(raw.get('settings', {}).get('timezone', 'Instance timezone'))[:100],
                              'rules': [{k: rule[k] for k in ('field', 'expression', 'minutesInterval', 'hoursInterval', 'triggerAtHour', 'triggerAtMinute', 'daysInterval') if k in rule}
                                        for rule in params.get('rule', {}).get('interval', [])[:20]]})
        if slug in {'executeWorkflow', 'toolWorkflow'}:
            ref = params.get('workflowId', '')
            ref = ref.get('value', '') if isinstance(ref, dict) else ref
            if isinstance(ref, str) and ref and not ref.startswith('='):
                children.append(ref)
    identity = str(raw['id'])
    return {'id': identity, 'name': str(raw.get('name', identity))[:200], 'active': bool(raw.get('active')), 'archived': bool(raw.get('isArchived')),
            'updated_at': raw.get('updatedAt', ''), 'url': origin + '/workflow/' + quote(identity, safe=''),
            'applications': list(apps.values()), 'schedules': schedules, 'subworkflows': children,
            'node_count': len(raw.get('nodes', []))}


def discover(user, query=''):
    connection, client, _ = context(user)
    data = client.agents(query)
    return {'items': [{k: a.get(k) for k in ('id', 'name', 'published', 'availableInMCP', 'projectId')} for a in data.get('data', [])],
            'bounded': len(data.get('data', [])) >= 100, 'site': connection['site']}


def link(user, raw):
    remote_id = raw.get('remote_id')
    if not isinstance(remote_id, str) or not 1 <= len(remote_id) <= 200:
        raise HTTPException(422, 'Choose an n8n agent.')
    connection, client, _ = context(user)
    remote = client.agent(remote_id)
    identity = 'n8n-' + key(user, connection['site'], remote_id)
    db = service.initialize()
    try:
        old = db.get(identity)
    except KeyError:
        old = None
    if old:
        try:
            return {**refresh(user, identity), 'existing': True}
        except HTTPException:
            return {'item': old, 'existing': True, 'warning': 'Existing agent linked. Refresh n8n details to load dependencies.'}
    try:
        profile = service.validate({**raw.get('profile', {}), 'runtime': 'n8n'})
    except (ValueError, TypeError):
        raise HTTPException(422, 'Check the agent profile fields.') from None
    item = db.save({**profile, 'remote_id': remote_id, 'connector_user': user,
                    'connector_site': connection['site'], 'remote_name': remote.get('agent', {}).get('name', profile['name']),
                    **({'mock': True, 'demo_user': user} if connection.get('mock') else {})}, identity=identity, seed=True)
    # Linking is durable even if the subsequent inventory request fails.
    try:
        return refresh(user, identity)
    except HTTPException:
        return {'item': item, 'warning': 'Agent linked. Refresh n8n details to load dependencies.'}


def refresh(user, identity):
    connection, client, old = context(user, identity)
    library = bool(old.get('n8n_library'))
    from modules.integrations.n8n import browser_origin
    origin = browser_origin(connection.get('public_url', '')) or connection['site']
    remote = {'agent': {'name': 'n8n workflow library'}, 'config': {}} if library else client.agent(old['remote_id'])
    config, info = remote.get('config', {}), remote.get('agent', {})
    inventory, bounded = workflows(client)
    refs = [t.get('workflow') for t in config.get('tools', []) if t.get('type') == 'workflow']
    selected = inventory if library else [w for w in inventory if w.get('name') in refs or w.get('id') in refs]
    warnings = []
    if bounded:
        warnings.append('Workflow catalogue limited to 1,000 results; dependencies may be incomplete.')
    for ref in refs:
        if not any(w.get('name') == ref or w.get('id') == ref for w in selected):
            warnings.append('A workflow tool could not be resolved from the accessible catalogue.')
    views = [workflow_view(w, origin) for w in selected]
    # Include referenced sub-workflows, with a finite depth/cycle bound.
    visited = {w['id'] for w in views}
    for view in views:
        for child in view['subworkflows']:
            found = next((w for w in inventory if w['id'] == child), None)
            if found and child not in visited and len(views) < 100:
                views.append(workflow_view(found, origin)); visited.add(child)
            elif not found:
                warnings.append('A sub-workflow is unavailable or dynamically resolved.')
    executions = []
    if len(views) > 25:
        warnings.append('Execution history is limited to the first 25 linked workflows.')
    for view in views[:25]:
        try:
            page = client.request('GET', '/executions', params={'workflowId': view['id'], 'limit': 20, 'includeData': 'false'})
            for execution in page.get('data', []):
                executions.append({'id': str(execution['id']), 'workflow_id': view['id'], 'workflow_name': view['name'],
                                   'status': str(execution.get('status', 'unknown'))[:50],
                                   'started_at': execution.get('startedAt'), 'stopped_at': execution.get('stoppedAt'),
                                   'url': origin + '/workflow/' + quote(view['id'], safe='') + '/executions/' + quote(str(execution['id']), safe='')})
            if page.get('nextCursor'):
                warnings.append('Showing the latest 20 executions per workflow; older history is not imported.')
        except HTTPException:
            warnings.append('Execution history unavailable. Check executions:read permission.')
    snapshot = {'name': str(info.get('name', config.get('name', old['remote_name'])))[:120],
                'url': (origin + '/projects/' + quote(str(info['projectId']), safe='') + '/agents/' + quote(old['remote_id'], safe='')) if info.get('projectId') else '',
                'instructions': str(config.get('instructions', ''))[:20000],
                'config_hash': remote.get('configHash', ''), 'published': bool(info.get('published')),
                'runnable': bool(remote.get('isRunnable')), 'updated_at': info.get('updatedAt', ''),
                'synced_at': now(), 'workflows': views, 'executions': executions,
                'schedules': [{k: t.get(k) for k in ('id', 'name', 'cronExpression', 'timezone', 'enabled')} for t in remote.get('tasks', [])[:50]],
                'warnings': list(dict.fromkeys(warnings)), 'can_edit': not library and 'mutate_agent' in client._mcp()}
    # Remote source fields are separate from legacy Fleet presentation fields.
    item = service.store().save({**old, 'remote_name': snapshot['name'], 'n8n_snapshot': snapshot}, identity=identity, version=old['version'])
    return {'item': item}


def edit(user, identity, raw):
    _, client, old = context(user, identity)
    if old.get('n8n_library'):
        raise HTTPException(422, 'The workflow library is an inventory, not an n8n agent.')
    if type(raw.get('version')) is not int or raw['version'] != old['version']:
        raise HTTPException(409, 'Fleet changed. Refresh before saving.')
    if set(raw) - {'version', 'config_hash', 'name', 'instructions'}:
        raise HTTPException(422, 'Only the draft name and instructions can be edited here.')
    for field, maximum in [('name', 120), ('instructions', 20000)]:
        if not isinstance(raw.get(field), str) or not raw[field].strip() or len(raw[field]) > maximum:
            raise HTTPException(422, 'Enter a valid ' + field + '.')
    remote = client.agent(old['remote_id'])
    if not raw.get('config_hash') or raw['config_hash'] != remote.get('configHash'):
        raise HTTPException(409, 'n8n changed since your last refresh. Refresh and review before saving.')
    client._mcp('mutate_agent', {'agentId': old['remote_id'], 'baseConfigHash': raw['config_hash'],
                              'operation': {'type': 'config.patch', 'patch': [
                                  {'op': 'add', 'path': '/' + k, 'value': raw[k].strip()} for k in ('name', 'instructions')]}})
    try:
        return refresh(user, identity)
    except (HTTPException, FleetConflict):
        raise HTTPException(502, 'Draft saved in n8n, but refresh failed. Refresh to reconcile; do not resubmit.') from None


def capture(user, identity):
    connection, _, item = context(user, identity)
    db = service.store()
    event_ids = []
    for run in item.get('n8n_snapshot', {}).get('executions', []):
        if run['status'] not in {'success', 'error', 'canceled', 'crashed'}:
            continue
        event_id = 'n8n-execution:' + key(user, connection['site'], run['id'])
        payload = {'kind': 'n8n-execution', 'agent_name': item['name'], 'execution_id': run['id'],
                   'workflow_id': run['workflow_id'], 'workflow_name': run['workflow_name'],
                   'status': run['status'], 'started_at': run['started_at'], 'stopped_at': run['stopped_at'],
                   'url': run['url'], 'mock': bool(item.get('mock'))}
        db.event(event_id, identity, payload)
        event_ids.append(event_id)
    from modules.agents.audit import deliver_pending
    receipt = deliver_pending(event_ids)
    return {'eligible': len(event_ids), **receipt, 'preview': os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') == '1'}


def extend_graph(agents, nodes, edge, add):
    for agent in agents:
        snapshot = agent.get('n8n_snapshot')
        if not snapshot:
            continue
        aid = agent['id']
        scope = key(agent.get('connector_user'), agent.get('connector_site'))
        def put(kind, rid, label, summary='', url='', **extra):
            identity = 'n8n:' + scope + ':' + kind + ':' + rid
            add(aid, identity, kind, label, summary, url, snapshot['synced_at'],
                relation='observes' if kind == 'task' else 'linked', source='n8n', mock=agent.get('mock', False), **extra)
            return identity
        for workflow in snapshot['workflows']:
            wid = put('workflow', workflow['id'], workflow['name'], str(workflow['node_count']) + ' nodes · dependency types inferred from workflow definitions', workflow['url'], state='archived' if workflow.get('archived') else 'active' if workflow['active'] else 'inactive')
            for app in workflow['applications']:
                appid = put(app.get('kind', 'application'), app['id'], app['name'], 'Workflow node type · connection health not tested')
                edge(wid, appid, 'uses')
            for schedule in workflow['schedules']:
                sid = put('trigger', workflow['id'] + ':' + schedule['id'], schedule['name'], json.dumps(schedule['rules']) + ' · ' + schedule['timezone'], workflow['url'], state='enabled' if schedule['enabled'] else 'disabled')
                edge(sid, wid, 'triggers')
            for child in workflow['subworkflows']:
                edge(wid, 'n8n:' + scope + ':workflow:' + child, 'calls')
        for schedule in snapshot['schedules']:
            put('trigger', aid + ':' + str(schedule['id']), schedule.get('name') or 'Agent schedule', (schedule.get('cronExpression') or '') + ' · ' + (schedule.get('timezone') or 'Instance timezone'), state='enabled' if schedule.get('enabled') else 'disabled')
        for run in snapshot['executions']:
            rid = put('task', run['id'], run['workflow_name'] + ' · ' + run['status'], 'Started ' + str(run['started_at']) + ' · Finished ' + str(run['stopped_at']), run['url'], state=run['status'])
            if rid in nodes and isinstance(nodes[rid], dict):
                nodes[rid]['created'] = run['started_at'] or snapshot['synced_at']
            edge('n8n:' + scope + ':workflow:' + run['workflow_id'], rid, 'execution')
        for event in service.store().events(aid):
            payload = event['payload']
            if payload.get('kind') != 'n8n-execution':
                continue
            eid = put('entry', event['id'], payload['workflow_name'] + ' · activity entry',
                      ('Preview receipt only; production corpus untouched.' if payload.get('mock') else
                       'Recorded in Activity Corpus' if event['delivered'] else 'Queued for Activity Corpus'),
                      payload['url'], state='preview' if payload.get('mock') else 'recorded' if event['delivered'] else 'pending')
            edge('n8n:' + scope + ':task:' + payload['execution_id'], eid, 'captured as')
