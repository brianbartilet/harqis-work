from uuid import uuid4

import pytest


@pytest.fixture
def bridge(monkeypatch, tmp_path):
    from modules.hfl_corpus import agent_bridge as module
    from workflows.hfl.agent_bridge_store import AgentBridgeStore
    from workflows.hfl.timeline_store import FollowUpStore
    monkeypatch.setenv('HFL_TIMELINE_LOCAL_PREVIEW', '1')
    monkeypatch.setenv('HFL_AGENT_BRIDGE_TOKEN', 'test-worker-token')
    store = AgentBridgeStore(tmp_path / 'bridge.sqlite3')
    actions = FollowUpStore(tmp_path / 'actions.sqlite3')
    monkeypatch.setattr(module, 'bridge_store', lambda: store)
    monkeypatch.setattr(module.timeline, 'store', lambda: actions)
    monkeypatch.setattr(module, 'deliver_pending', lambda: None)
    return module, store, actions


def create_action(actions):
    return actions.create({'request_id': str(uuid4()), 'title': 'Research a bridge', 'expected_outcome': 'A supported design', 'prompt': 'Review the official docs.'}, actor='owner')[0]


def owner_headers():
    from modules.hfl_shares.security import make_csrf_token
    return {'X-CSRF-Token': make_csrf_token('frontend-test-user')}


WORKER = {'Authorization': 'Bearer test-worker-token'}


def start(client, item, auto=False):
    response = client.post(f"/hfl-corpus/agent-bridge/sources/actionable/{item['id']}/run", headers=owner_headers(), json={'request_key': str(uuid4()), 'auto_complete': auto})
    assert response.status_code == 200, response.text
    run = response.json()
    claimed = client.post(f"/api/hfl-agent/runs/{run['id']}/claim", headers=WORKER, json={})
    assert claimed.status_code == 200, claimed.text
    return claimed.json()


def event(client, run, kind, payload, key=None):
    return client.post(f"/api/hfl-agent/runs/{run['id']}/events", headers=WORKER,
                       json={'lease_token': run['lease_token'], 'event_key': key or kind, 'kind': kind, 'payload': payload})


RESULT = {'summary': 'Design completed with cited documentation.', 'evidence': ['https://example.org/docs'], 'complete': True}


def test_agent_run_updates_status_records_events_and_requires_acceptance(bridge, authenticated_client):
    module, store, actions = bridge
    item = create_action(actions)
    run = start(authenticated_client, item)
    assert actions.get(item['id'])['status'] == 'in_progress'
    assert actions.history(item['id'])[0]['actor'].startswith('agent:hermes:')
    assert 'lease_token' not in store.get(run['id'])
    assert event(authenticated_client, run, 'succeeded', RESULT).status_code == 400
    assert event(authenticated_client, run, 'plan', {'summary': 'Compare the documented boundaries.'}).status_code == 200
    assert event(authenticated_client, run, 'succeeded', RESULT).json()['state'] == 'review'
    assert actions.get(item['id'])['status'] == 'in_progress'
    accepted = authenticated_client.post(f"/hfl-corpus/agent-bridge/runs/{run['id']}/accept", headers=owner_headers(), json={})
    assert accepted.status_code == 200, accepted.text
    assert actions.get(item['id'])['status'] == 'done'
    assert len(actions.history(item['id'])) == 3
    assert [row['kind'] for row in store.events('actionable:' + item['id'])] == ['succeeded', 'accepted', 'succeeded', 'plan', 'running', 'queued']
    assert event(authenticated_client, run, 'succeeded', RESULT).status_code == 200
    assert event(authenticated_client, run, 'succeeded', {**RESULT, 'summary': 'Changed'}).status_code == 409


def test_concurrent_claim_and_owner_edit_cannot_be_overwritten(bridge, authenticated_client):
    module, store, actions = bridge
    item = create_action(actions)
    run = start(authenticated_client, item, auto=True)
    assert authenticated_client.post(f"/api/hfl-agent/runs/{run['id']}/claim", headers=WORKER, json={}).status_code == 409
    actions.update(item['id'], {'version': 2, 'prompt': 'A different task'}, actor='owner')
    event(authenticated_client, run, 'plan', {'summary': 'Plan'})
    assert event(authenticated_client, run, 'succeeded', RESULT).json()['state'] == 'review'
    assert actions.get(item['id'])['prompt'] == 'A different task'
    assert actions.get(item['id'])['status'] == 'in_progress'
    assert authenticated_client.post(f"/hfl-corpus/agent-bridge/runs/{run['id']}/accept", headers=owner_headers(), json={}).status_code == 409


def test_cancellation_and_expired_leases_reject_late_results(bridge, authenticated_client):
    module, store, actions = bridge
    run = start(authenticated_client, create_action(actions))
    assert authenticated_client.post(f"/hfl-corpus/agent-bridge/runs/{run['id']}/cancel", headers=owner_headers(), json={}).status_code == 200
    assert event(authenticated_client, run, 'progress', {'summary': 'Late'}).status_code == 409
    second = start(authenticated_client, create_action(actions))
    with store.connect() as db:
        db.execute("UPDATE agent_requests SET lease_until='2000-01-01' WHERE id=?", (second['id'],))
    assert event(authenticated_client, second, 'heartbeat', {}).status_code == 409
    store.expire()
    assert store.get(second['id'])['state'] == 'failed'
    assert store.get(second['id'])['delivery'] == 'pending'


def test_auth_and_csrf_do_not_expose_worker_authority(bridge, authenticated_client):
    module, store, actions = bridge
    item = create_action(actions)
    path = f"/hfl-corpus/agent-bridge/sources/actionable/{item['id']}/run"
    assert authenticated_client.post(path, json={'request_key': 'a'}).status_code == 403
    assert authenticated_client.get('/api/hfl-agent/queue').status_code == 401
    assert authenticated_client.get('/api/hfl-agent/queue', headers={'Authorization': 'Bearer frontend-test-hfl-api-token'}).status_code == 401
    authenticated_client.cookies.clear()
    assert authenticated_client.get(path.rsplit('/', 1)[0]).status_code == 401
    assert authenticated_client.post(path, headers=WORKER, json={'request_key': 'a'}).status_code == 401


def test_daily_opt_in_and_duplicate_requests(bridge):
    module, store, actions = bridge
    item = create_action(actions)
    assert module.sweep()['runs'] == []
    store.subscribe('actionable', item['id'], 'daily', False)
    first = module.sweep()['runs']
    assert len(first) == 1
    assert module.sweep()['runs'] == first
    manual = module.enqueue('actionable', item['id'], 'manual', 'owner')
    assert manual['id'] == first[0]
    assert len(store.list()) == 1


def test_pin_receipt_preserves_dispatch_guidance_after_edit_and_archive(bridge):
    module, store, actions = bridge
    pins = module.get_memory_pin_store()
    pins.save_category(category_id=None, name='Research', color='#f59e0b', instructions='Cite sources')
    category = pins.snapshot()['categories'][0]
    pins.save_range(range_id=None, category_id=category['id'], start_date='2026-09-10', end_date='2026-09-11', note='', title='Weekly review', prompt='Summarize this period')
    pin = pins.snapshot()['ranges'][0]
    run = module.enqueue('pin', str(pin['id']), 'pin-request', 'owner')
    pins.save_category(category_id=category['id'], name='Research', color='#f59e0b', instructions='New guidance')
    pins.archive_category(category['id'])
    pins.record_execution_snapshot({**run, 'state': 'review', 'result': RESULT, 'agent': 'hermes'})
    pins.record_execution_snapshot({**run, 'state': 'review', 'result': RESULT, 'agent': 'hermes'})
    history = pins.agent_history(category['id'])
    assert len(history) == 1
    assert history[0]['system_prompt'] == 'Cite sources'
    assert history[0]['instructions'] == 'Summarize this period'


def test_stale_instructions_cancel_before_claim(bridge, authenticated_client):
    module, store, actions = bridge
    item = create_action(actions)
    run = module.enqueue('actionable', item['id'], 'stale', 'owner')
    actions.update(item['id'], {'version': 1, 'prompt': 'Changed'}, actor='owner')
    response = authenticated_client.post(f"/api/hfl-agent/runs/{run['id']}/claim", headers=WORKER, json={})
    assert response.status_code == 409
    assert store.get(run['id'])['state'] == 'cancelled'
    assert actions.get(item['id'])['status'] == 'open'


def test_after_period_schedule_runs_once_and_ignores_future_pins(bridge):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    module, store, actions = bridge
    pins = module.get_memory_pin_store()
    pins.save_category(category_id=None, name='Review', color='#f59e0b')
    category = pins.snapshot()['categories'][0]
    today = datetime.now(ZoneInfo('Asia/Singapore')).date()
    for day in (today - timedelta(days=1), today + timedelta(days=1)):
        pins.save_range(range_id=None, category_id=category['id'], start_date=day.isoformat(), end_date=day.isoformat(), title='Review', prompt='Review this period')
    past, future = pins.snapshot()['ranges']
    for pin in (past, future):
        store.subscribe('pin', str(pin['id']), 'after_period', False)
    result = module.sweep()['runs']
    assert len(result) == 1
    assert store.get(result[0])['source_key'] == 'pin:' + str(past['id'])
    store.owner_transition(result[0], 'cancelled', 'owner', 'Keep the receipt')
    assert module.sweep()['runs'] == result
    assert len(store.list()) == 1


def test_corpus_context_excludes_protected_linked_entry(bridge, monkeypatch):
    from types import SimpleNamespace
    module, store, actions = bridge
    entry = SimpleNamespace(text='Entry ID: hfl-secret\nPrivate information', tags=('secrets',), secret=False)
    monkeypatch.setattr(module.corpus_index, 'get', lambda path: SimpleNamespace(entries=[entry]))
    context = module.evidence_context({'kind': 'actionable', 'source': {'source': {'path': 'note.md', 'entry_id': 'hfl-secret'}}})
    assert context['entries'] == []


def test_receipt_failure_retries_from_durable_request(bridge, monkeypatch):
    import importlib
    module, store, actions = bridge
    delivery = importlib.reload(module).deliver_pending
    monkeypatch.setattr(module, 'bridge_store', lambda: store)
    from workflows.hfl import persistence
    item = create_action(actions)
    snapshot = {'kind': 'actionable', 'source_id': item['id'], 'source_key': 'actionable:' + item['id'], 'source': item, 'instruction_hash': 'test'}
    run = store.enqueue(snapshot, 'delivery-test', 'owner')
    run = store.claim(run['id'], 'hermes')
    store.report(run['id'], 'hermes', run['lease_token'], 'plan', 'plan', {'summary': 'Plan'})
    store.report(run['id'], 'hermes', run['lease_token'], 'result', 'succeeded', RESULT)
    monkeypatch.delenv('HFL_TIMELINE_LOCAL_PREVIEW')
    calls = []
    def submit(entry, **kwargs):
        calls.append(kwargs['dedup_key'])
        if len(calls) == 1:
            raise OSError('Unavailable')
        return {'delivery': 'outbox'}
    monkeypatch.setattr(persistence, 'submit_hfl_entry', submit)
    delivery()
    assert store.get(run['id'])['delivery'] == 'pending'
    delivery()
    delivery()
    assert store.get(run['id'])['delivery'] == 'delivered'
    assert calls == ['agent-run:' + run['id']] * 2


def test_browser_review_lifecycle_and_mobile_layout(bridge, authenticated_client, tmp_path):
    from pathlib import Path
    from urllib.parse import urlparse
    from modules.hfl_shares.security import make_csrf_token
    playwright = pytest.importorskip('playwright.sync_api')
    module, store, actions = bridge
    item = create_action(actions)
    csrf = make_csrf_token('frontend-test-user')
    html = '<html><body style="background:#050a1b;color:#e2e8f0;font-family:Arial"><script type="application/json" data-memory-csrf>"' + csrf + '"</script></body></html>'
    frontend = Path(__file__).resolve().parents[1]
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel='chrome', headless=True)
        except playwright.Error:
            pytest.skip('An installed Chrome browser is required for visual regression.')
        page = browser.new_page(viewport={'width': 1100, 'height': 850})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def route(request_route):
            request = request_route.request
            if '/hfl-corpus/agent-bridge/' not in request.url:
                request_route.fulfill(status=200, content_type='text/html', body=html)
                return
            response = authenticated_client.request(request.method, urlparse(request.url).path, content=request.post_data,
                                                    headers={key: value for key, value in request.headers.items() if key.lower() in {'content-type', 'x-csrf-token'}})
            request_route.fulfill(status=response.status_code, content_type='application/json', body=response.content)
        page.route('https://bridge.test/**', route)
        page.goto('https://bridge.test/')
        page.add_style_tag(path=str(frontend / 'static/css/hfl-timeline.css'))
        page.add_script_tag(path=str(frontend / 'static/js/hfl-agent-bridge.js'))
        page.evaluate('(item) => window.hflAgentBridge.open("actionable", item.id, item.title)', item)
        page.get_by_role('button', name='Run now', exact=True).click()
        page.get_by_text('Waiting for the Hermes worker.').wait_for()
        run_id = store.list()[0]['id']
        run = authenticated_client.post(f'/api/hfl-agent/runs/{run_id}/claim', headers=WORKER, json={}).json()
        event(authenticated_client, run, 'plan', {'summary': 'Check the expected outcome.'})
        event(authenticated_client, run, 'succeeded', {**RESULT, 'summary': 'Draft ready. <img src=x onerror=alert(1)> is literal text.'})
        page.get_by_role('button', name='Refresh', exact=True).click()
        page.get_by_role('button', name='Accept and mark done').wait_for()
        page.screenshot(path=str(tmp_path / 'agent-bridge-desktop.png'))
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(tmp_path / 'agent-bridge-mobile.png'))
        assert page.locator('dialog img').count() == 0
        assert page.locator('dialog').evaluate('(el) => el.scrollWidth <= el.clientWidth')
        page.get_by_role('button', name='Accept and mark done').click()
        page.get_by_role('heading', name='succeeded', exact=True).wait_for()
        assert actions.get(item['id'])['status'] == 'done'
        assert errors == []
        browser.close()
