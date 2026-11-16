"""Deterministic n8n double, enabled only in an isolated localhost preview."""
import copy
import json
import os
from pathlib import Path
from fastapi import HTTPException
from modules.integrations.n8n_fleet import key
from workflows.hfl.agent_fleet_store import now


def path(user):
    if os.getenv('HARQIS_N8N_MOCK') != '1' or os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') != '1':
        raise HTTPException(404, 'Preview unavailable.')
    root = Path(os.environ['HARQIS_DATA_ROOT']) / 'n8n-mock'
    root.mkdir(parents=True, exist_ok=True)
    return root / (key(user) + '.json')


def seed(user):
    target = path(user)
    if not target.exists():
        data = {'name': 'Atlas · HARQIS Operations', 'instructions': 'Find approved workflows, explain their dependencies, and report execution results. Ask before consequential actions.', 'revision': 1}
        target.write_text(json.dumps(data), encoding='utf-8')
    return json.loads(target.read_text('utf-8'))


def change(user):
    data = seed(user)
    data.update(name='Atlas · Operations revised in n8n', revision=data['revision'] + 1)
    path(user).write_text(json.dumps(data), encoding='utf-8')
    return {'message': 'Mock n8n changed. Refresh the linked agent; an older draft will be rejected.'}


class MockN8n:
    def __init__(self, user):
        self.user = user

    def agents(self, query=''):
        data = seed(self.user)
        return {'data': [{'id': 'atlas', 'name': data['name'], 'published': True, 'availableInMCP': True, 'projectId': 'operations'}] if query.lower() in data['name'].lower() else []}

    def agent(self, identity):
        if identity != 'atlas':
            raise HTTPException(404, 'Agent unavailable.')
        data = seed(self.user)
        return {'agent': {'id': 'atlas', 'projectId': 'operations', 'name': data['name'], 'published': True, 'updatedAt': now()},
                'config': {'name': data['name'], 'instructions': data['instructions'], 'tools': [
                    {'type': 'workflow', 'workflow': 'Morning operations briefing'},
                    {'type': 'workflow', 'workflow': 'Invoice reconciliation'}]},
                'configHash': str(data['revision']), 'isRunnable': True,
                'tasks': [{'id': 'morning', 'name': 'Morning operations review', 'cronExpression': '0 9 * * 1-5', 'timezone': 'Asia/Singapore', 'enabled': True}]}

    def _mcp(self, tool=None, arguments=None):
        if not tool:
            return ['search_agents', 'get_agent', 'mutate_agent']
        if tool != 'mutate_agent':
            raise HTTPException(409, 'Unsupported preview operation.')
        data = seed(self.user)
        if str(data['revision']) != arguments['baseConfigHash']:
            raise HTTPException(409, 'Mock n8n changed. Refresh before saving.')
        for patch in arguments['operation']['patch']:
            data[patch['path'].lstrip('/')] = patch['value']
        data['revision'] += 1
        path(self.user).write_text(json.dumps(data), encoding='utf-8')
        return {'ok': True, 'configHash': str(data['revision'])}

    def request(self, method, path, *, params=None, json=None):
        if method != 'GET':
            raise HTTPException(409, 'Preview execution is disabled.')
        if path == '/workflows':
            return {'data': copy.deepcopy(WORKFLOWS)}
        if path == '/executions':
            wid = params['workflowId']
            return {'data': [{'id': wid + '-run-' + str(i), 'workflowId': wid, 'status': status,
                              'startedAt': '2026-11-16T01:00:00+00:00', 'stoppedAt': '2026-11-16T01:00:12+00:00'}
                             for i, status in enumerate(['success', 'error'])]}
        raise HTTPException(404, 'Preview resource unavailable.')


def connection(user):
    seed(user)
    return {'site': 'https://n8n.example.test', 'mock': True}, MockN8n(user)


WORKFLOWS = [
    {'id': 'briefing', 'name': 'Morning operations briefing', 'active': True, 'settings': {'timezone': 'Asia/Singapore'}, 'nodes': [
        {'id': 'timer', 'name': 'Weekday briefing', 'type': 'n8n-nodes-base.scheduleTrigger', 'parameters': {'rule': {'interval': [{'field': 'cronExpression', 'expression': '0 9 * * 1-5'}]}}},
        {'type': 'n8n-nodes-base.googleCalendar'}, {'type': 'n8n-nodes-base.slack'},
        {'type': 'n8n-nodes-base.executeWorkflow', 'parameters': {'workflowId': {'value': 'health'}}}]},
    {'id': 'invoices', 'name': 'Invoice reconciliation', 'active': False, 'nodes': [
        {'type': 'n8n-nodes-base.executeWorkflowTrigger'}, {'type': 'n8n-nodes-base.googleSheets'},
        {'type': 'n8n-nodes-base.gmail'}, {'type': 'n8n-nodes-base.code'}]},
    {'id': 'health', 'name': 'HARQIS service health', 'active': True, 'nodes': [
        {'type': 'n8n-nodes-base.executeWorkflowTrigger'}, {'type': 'n8n-nodes-base.httpRequest'}]},
]
