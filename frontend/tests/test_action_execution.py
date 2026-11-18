"""Provider receipts, migration ownership and scoped Butler handoffs."""
import json
import uuid

import pytest
from fastapi import HTTPException

from frontend.tests.test_agent_fleet import fleet
from frontend.tests.test_hfl_agent_bridge import bridge, create_action, owner_headers
from modules.hfl_corpus import action_execution as execution, action_agents
from modules.integrations import nod


@pytest.fixture
def provider(fleet, bridge, monkeypatch):
    agent = fleet.initialize().save({**fleet.defaults('Nod executor'), 'runtime': 'nod',
        'connector_provider': 'nod', 'connector_user': 'frontend-test-user', 'connector_site': 'http://localhost:3000'}, identity='nod-test', seed=True)
    view = {'thread_id': str(uuid.uuid4()), 'binding': 'test-binding', 'url': 'http://localhost:3000',
            'active': True, 'ready': True, 'mock': False, 'needs_private_input': False, 'messages': [], 'turns': []}
    posts = []
    def send(user, identity, raw):
        posts.append(raw)
        turn_id = str(uuid.uuid4())
        view['messages'].append({'id': raw['request_id'], 'turnId': turn_id, 'role': 'user', 'text': raw['text']})
        view['turns'].append({'id': turn_id, 'status': 'running'})
        return {'threadId': view['thread_id'], 'messageId': raw['request_id'], 'turnId': turn_id}
    monkeypatch.setattr(nod, 'state', lambda *args: view)
    monkeypatch.setattr(nod, 'send', send)
    from modules.integrations import store as connectors
    connectors.save('frontend-test-user', 'nod', {'enabled': True, 'site': 'http://localhost:3000'})
    monkeypatch.setattr(bridge[0], 'evidence_context', lambda snapshot: {})
    return agent, view, posts


def assigned(bridge, provider, *, ready=True):
    item = create_action(bridge[2])
    action_agents.store().configure('card:' + item['id'], {'assignment_mode': 'agent', 'agent_id': provider[0]['id']})
    return bridge[2].update(item['id'], {'version': item['version'], 'status': 'active' if ready else 'open', 'agent_enabled': True}, actor='owner')


def finish(provider, *, complete=True):
    view = provider[1]
    turn = view['turns'][-1]
    turn['status'] = 'succeeded'
    view['messages'].append({'id': str(uuid.uuid4()), 'turnId': turn['id'], 'role': 'assistant',
        'text': json.dumps({'summary': 'Synthetic work verified.', 'complete': complete, 'evidence': ['test:output']})})


def test_nod_ready_receipt_completion_and_idempotency(bridge, provider):
    item = assigned(bridge, provider)
    execution.tick()
    assert len(provider[2]) == 1
    assert bridge[2].get(item['id'])['status'] == 'active'
    execution.tick()
    assert bridge[2].get(item['id'])['status'] == 'in_progress'
    finish(provider)
    execution.tick()
    assert bridge[2].get(item['id'])['status'] == 'done'
    execution.tick()
    assert len(provider[2]) == 1
    assert execution.store().list('actionable:' + item['id'])[0]['result']['complete']


def test_ambiguous_acceptance_reconciles_without_resending(bridge, provider, monkeypatch):
    assigned(bridge, provider)
    send = nod.send
    def lose_response(*args):
        send(*args)
        raise HTTPException(502, 'Timeout after acceptance')
    monkeypatch.setattr(nod, 'send', lose_response)
    execution.tick()
    assert execution.store().receipts()[0]['state'] == 'unknown'
    execution.tick()
    assert execution.store().receipts()[0]['receipt']['turnId']
    assert len(provider[2]) == 1


def test_ambiguous_missing_receipt_keeps_slot(bridge, provider, monkeypatch):
    assigned(bridge, provider)
    monkeypatch.setattr(nod, 'send', lambda *args: (_ for _ in ()).throw(HTTPException(502, 'Timeout')))
    execution.tick()
    execution.tick()
    assert execution.store().receipts()[0]['state'] == 'unknown'
    assert len(execution.store().receipts()) == 1


def test_shared_conversation_serializes_and_manual_closure_wins(bridge, provider):
    first = assigned(bridge, provider)
    second = assigned(bridge, provider)
    execution.tick()
    assert len(provider[2]) == 1
    execution.tick()
    run = next(r for r in execution.store().list() if r['state'] == 'running')
    item = bridge[2].get(run['snapshot']['source_id'])
    bridge[2].update(item['id'], {'version': item['version'], 'status': 'dismissed'}, actor='owner')
    finish(provider)
    execution.tick()
    assert bridge[2].get(item['id'])['status'] == 'dismissed'
    assert len(provider[2]) == 2


def test_hermes_cannot_claim_nod_run(bridge, provider, authenticated_client):
    item = assigned(bridge, provider)
    run = execution.trigger(item['id'], 'manual-test', 'frontend-test-user')
    headers = {'Authorization': 'Bearer test-worker-token'}
    assert run['id'] not in [r['id'] for r in authenticated_client.get('/api/hfl-agent/queue', headers=headers).json()['runs']]
    assert authenticated_client.post('/api/hfl-agent/runs/' + run['id'] + '/claim', headers=headers, json={}).status_code == 409


def test_butler_nod_handoff_scope_and_review(bridge, provider, authenticated_client):
    item = create_action(bridge[2])
    action_agents.store().configure('card:' + item['id'], {'assignment_mode': 'butler', 'agent_id': 'butler', 'permitted_agent_ids': [provider[0]['id']]})
    parent = execution.trigger(item['id'], 'parent', 'frontend-test-user')
    headers = {'Authorization': 'Bearer test-worker-token'}
    response = authenticated_client.post('/api/hfl-agent/runs/' + parent['id'] + '/claim', headers=headers, json={})
    assert response.status_code == 200, response.text
    parent = response.json()
    scoped = {'Authorization': 'Bearer ' + parent['delegation_token']}
    endpoint = '/api/hfl-agent/delegation/' + parent['id']
    payload = {'agent_id': provider[0]['id'], 'prompt': 'Return a synthetic summary.', 'request_key': 'summary'}
    child_response = authenticated_client.post(endpoint, headers=scoped, json=payload)
    assert child_response.status_code == 200, child_response.text
    child = child_response.json()
    assert authenticated_client.post(endpoint, headers=scoped, json=payload).json()['id'] == child['id']
    assert authenticated_client.post(endpoint, headers=headers, json=payload).status_code == 403
    assert authenticated_client.post(endpoint, headers=scoped, json={**payload, 'agent_id': 'butler'}).status_code == 400
    execution.tick()
    execution.tick()
    finish(provider)
    execution.tick()
    assert execution.store().get(child['id'])['state'] == 'succeeded'
    assert bridge[2].get(item['id'])['status'] == 'in_progress'
    result = {'summary': 'Reviewed Nod output.', 'complete': True, 'evidence': ['child:' + child['id']]}
    with pytest.raises(ValueError, match='Review every'):
        execution.review_children(parent, result)
    execution.review_children(parent, {**result, 'reviewed_child_ids': [child['id']]})
    event_url = '/api/hfl-agent/runs/' + parent['id'] + '/events'
    common = {'lease_token': parent['lease_token']}
    assert authenticated_client.post(event_url, headers=headers, json={**common, 'event_key': 'plan', 'kind': 'plan', 'payload': {'summary': 'Delegate the summary and review its evidence.'}}).status_code == 200
    assert authenticated_client.post(event_url, headers=headers, json={**common, 'event_key': 'result', 'kind': 'succeeded', 'payload': result}).status_code == 400
    response = authenticated_client.post(event_url, headers=headers, json={**common, 'event_key': 'result', 'kind': 'succeeded', 'payload': {**result, 'reviewed_child_ids': [child['id']]}})
    assert response.status_code == 200, response.text
    assert bridge[2].get(item['id'])['status'] == 'done'
    assert authenticated_client.get(endpoint, headers=scoped).status_code == 403


def test_completion_requires_evidence():
    kind, result = execution.outcome([{'role': 'assistant', 'text': 'Message accepted.'}])
    assert kind == 'awaiting_input'
    assert result['blocked_reason'] == 'input'


def test_hermes_reserved_child_capacity(tmp_path):
    from workflows.hfl.agent_bridge_store import AgentBridgeStore, BridgeConflict
    db = AgentBridgeStore(tmp_path / 'capacity.sqlite')
    def queued(key, parent=None):
        snapshot = {'source_key': key, 'instruction_hash': key}
        if parent:
            snapshot['delegation'] = {'parent_run_id': parent}
        return db.enqueue(snapshot, key, 'test')['id']
    parent = queued('parent')
    db.claim(parent, 'hermes', concurrency=1)
    root = queued('other-root')
    with pytest.raises(BridgeConflict, match='capacity'):
        db.claim(root, 'hermes', concurrency=1)
    child = queued('child', parent)
    assert db.claim(child, 'hermes', concurrency=1)['state'] == 'running'
    second = queued('second-child', parent)
    with pytest.raises(BridgeConflict, match='capacity'):
        db.claim(second, 'hermes', concurrency=1)


def test_hermes_sweep_no_longer_discovers_actions(bridge, provider):
    assigned(bridge, provider)
    bridge[0].sweep()
    assert not execution.store().list()


def test_ready_validates_prompt_and_manual_actions_remain_manual(bridge, provider, authenticated_client):
    item = assigned(bridge, provider, ready=False)
    item = bridge[2].update(item['id'], {'version': item['version'], 'prompt': ''}, actor='owner')
    endpoint = '/hfl-corpus/timeline/items/' + item['id']
    response = authenticated_client.patch(endpoint, headers=owner_headers(), json={'version': item['version'], 'status': 'active'})
    assert response.status_code == 422
    assert 'Initial prompt' in response.text
    assert authenticated_client.patch(endpoint, headers=owner_headers(), json={'version': item['version'], 'status': 'active', 'agent_enabled': False}).status_code == 200


def test_approval_pauses_and_resumes_without_another_submission(bridge, provider):
    item = assigned(bridge, provider)
    execution.tick()
    execution.tick()
    view = provider[1]
    view['messages'].append({'id': str(uuid.uuid4()), 'turnId': view['turns'][0]['id'], 'role': 'assistant',
                             'text': 'Approve?', 'approval': {'state': 'pending'}})
    execution.tick()
    assert bridge[2].get(item['id'])['status'] == 'incomplete'
    view['messages'][-1]['approval']['state'] = 'approved'
    execution.tick()
    assert bridge[2].get(item['id'])['status'] == 'in_progress'
    finish(provider)
    execution.tick()
    assert bridge[2].get(item['id'])['status'] == 'done'
    assert len(provider[2]) == 1


def test_schedule_and_closed_replay(bridge, provider, authenticated_client):
    item = assigned(bridge, provider)
    endpoint = '/hfl-corpus/agent-bridge/actions/' + item['id'] + '/schedule'
    assert authenticated_client.post(endpoint, json={'enabled': True, 'minutes': 60}).status_code == 403
    assert authenticated_client.post(endpoint, headers=owner_headers(), json={'enabled': True, 'minutes': 0}).status_code == 400
    assert authenticated_client.post(endpoint, headers=owner_headers(), json={'enabled': True, 'minutes': 60}).status_code == 200
    execution.tick()
    run = execution.store().list()[0]
    assert run['request_key'].startswith('schedule:')
    execution.tick()
    finish(provider)
    execution.tick()
    assert bridge[2].get(item['id'])['status'] == 'done'
    assert execution.trigger(item['id'], run['request_key'], 'frontend-test-user')['id'] == run['id']
    execution.tick()
    assert len(provider[2]) == 1


def test_provider_slots_survive_reinstantiation(bridge, provider):
    item = assigned(bridge, provider)
    run = execution.trigger(item['id'], 'slot', 'frontend-test-user')
    assert execution.store().reserve(run['id'], 'one-installation', {'request_id': 'one'})
    other = assigned(bridge, provider)
    other_run = execution.trigger(other['id'], 'slot-two', 'frontend-test-user')
    assert not execution.store().reserve(other_run['id'], 'one-installation', {'request_id': 'two'})


def test_unresolved_release_requires_owner_evidence(bridge, provider, authenticated_client, monkeypatch):
    item = assigned(bridge, provider)
    monkeypatch.setattr(nod, 'send', lambda *args: (_ for _ in ()).throw(HTTPException(502, 'Timeout')))
    execution.tick()
    run = execution.store().list()[0]
    endpoint = '/hfl-corpus/agent-bridge/runs/' + run['id'] + '/resolve-provider'
    with pytest.raises(ValueError, match='still owns'):
        execution.trigger(item['id'], 'another-attempt', 'frontend-test-user')
    assert authenticated_client.post(endpoint, json={}).status_code == 403
    assert authenticated_client.post(endpoint, headers=owner_headers(), json={}).status_code == 400
    response = authenticated_client.post(endpoint, headers=owner_headers(), json={'confirmed_not_running': True, 'evidence': 'Inspected the synthetic provider: no message accepted.'})
    assert response.status_code == 200, response.text
    assert not execution.store().receipts()
    assert bridge[2].get(item['id'])['status'] == 'incomplete'


def test_celery_registration_and_schedule_ownership():
    from core.apps.sprout.app.celery import SPROUT
    from workflows.hfl.tasks_config import WORKFLOW_HFL
    from workflows.queues import WorkflowQueue
    name = 'workflows.hfl.tasks.action_execution.reconcile_action_executions'
    assert name in SPROUT.tasks
    entries = [v for v in WORKFLOW_HFL.values() if v['task'] == name]
    assert len(entries) == 1
    assert entries[0]['options']['queue'] == WorkflowQueue.HOST


def test_service_trigger_is_authenticated_and_idempotent(bridge, provider, authenticated_client):
    item = assigned(bridge, provider)
    endpoint = '/api/hfl-agent/actions/' + item['id'] + '/trigger'
    payload = {'request_key': 'service-trigger'}
    assert authenticated_client.post(endpoint, json=payload).status_code == 401
    headers = {'Authorization': 'Bearer test-worker-token'}
    first = authenticated_client.post(endpoint, headers=headers, json=payload)
    second = authenticated_client.post(endpoint, headers=headers, json=payload)
    assert first.status_code == 200, first.text
    assert first.json()['id'] == second.json()['id']


@pytest.mark.parametrize('width', [390, 1440])
def test_action_assignment_controls_browser(bridge, provider, authenticated_client, tmp_path, width):
    from pathlib import Path
    from urllib.parse import urlparse
    pw = pytest.importorskip('playwright.sync_api')
    from modules.hfl_shares.security import make_csrf_token
    root = Path(__file__).resolve().parents[1]
    html = '''<html><head><link rel="stylesheet" href="/static/css/hfl-timeline.css"></head><body>
      <script type="application/json" data-memory-csrf>CSRF</script>
      <dialog open class="agenda-dialog" style="width:min(90vw,650px);box-sizing:border-box"><form class="agenda-form-body">
      <textarea name="prompt">Synthetic task</textarea><textarea name="expected_outcome"></textarea>
      <details data-action-agent-settings><summary>Agent settings</summary>
      <p data-agent-settings-status></p><dl data-agent-settings-summary></dl><div data-agent-assignment-controls></div></details>
      </form></dialog><script src="/static/js/hfl-action-agent-settings.js"></script>
      <script>HflActionAgentSettings(document.querySelector('form'),null,{assignment_mode:'butler',agent_id:'butler'});document.querySelector('details').open=true;</script>
      </body></html>'''.replace('CSRF', json.dumps(make_csrf_token('frontend-test-user')))
    with pw.sync_playwright() as engine:
        browser = engine.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 1000})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        def route(r):
            path = urlparse(r.request.url).path
            if path == '/':
                r.fulfill(content_type='text/html', body=html)
                return
            response = authenticated_client.request(r.request.method, path, content=r.request.post_data_buffer,
                headers={k:v for k,v in r.request.headers.items() if k in {'content-type','x-csrf-token'}})
            r.fulfill(status=response.status_code, content_type=response.headers.get('content-type', 'text/plain'), body=response.content)
        page.route('https://actions.test/**', route)
        page.goto('https://actions.test/')
        page.get_by_label('Nod executor', exact=True).check()
        page.get_by_label('Scheduled discovery while Ready').check()
        page.get_by_label('Interval (minutes)').fill('30')
        draft = json.loads(page.evaluate("document.querySelector('form').actionAssignment.snapshot()"))
        assert draft['permitted_agent_ids'] == [provider[0]['id']]
        assert draft['schedule_minutes'] == 30 and draft['schedule_enabled']
        assert page.locator('dialog').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
        page.screenshot(path=str(tmp_path / ('action-assignment-' + str(width) + '.png')))
        assert not errors, errors
        browser.close()
