from uuid import uuid4

import pytest


@pytest.fixture
def bridge(monkeypatch, tmp_path):
    from modules.hfl_corpus import agent_bridge as module
    from workflows.hfl.agent_bridge_store import AgentBridgeStore
    from workflows.hfl.timeline_store import FollowUpStore
    monkeypatch.setenv('HFL_TIMELINE_LOCAL_PREVIEW', '1')
    monkeypatch.setenv('HFL_AGENT_BRIDGE_TOKEN', 'test-worker-token')
    monkeypatch.setenv('HFL_AGENT_BRIDGE_STORE_PATH', str(tmp_path / 'bridge.sqlite3'))
    store = AgentBridgeStore(tmp_path / 'bridge.sqlite3')
    actions = FollowUpStore(tmp_path / 'actions.sqlite3')
    monkeypatch.setattr(module, 'bridge_store', lambda: store)
    monkeypatch.setattr(module.timeline, 'store', lambda: actions)
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


def test_settings_persist_validate_and_require_owner_csrf(bridge, authenticated_client):
    from modules.app_settings.store import read_settings
    from modules.hfl_shares.security import make_csrf_token
    assert read_settings()['agent_mode'] == 'trusted'
    assert read_settings()['actions_polling_minutes'] == 30
    page = authenticated_client.get('/settings')
    assert page.status_code == 200 and 'Actions polling minutes' in page.text
    assert 'App Settings' in authenticated_client.get('/profile').text
    values = {'csrf': make_csrf_token('frontend-test-user'), 'actions_polling_minutes': '5', 'pin_backfill_days': '7'}
    assert authenticated_client.post('/settings', data=values).status_code == 200
    assert read_settings()['actions_polling_minutes'] == 5
    assert authenticated_client.post('/settings', data={**values, 'actions_polling_minutes': '0'}).status_code == 422
    assert authenticated_client.post('/settings', data={**values, 'csrf': ''}).status_code == 403
    authenticated_client.cookies.clear()
    assert authenticated_client.get('/settings', follow_redirects=False).status_code in {302, 303}


def test_polling_skips_blank_prompts_and_reopen_creates_fresh_attempt(bridge, authenticated_client):
    module, store, actions = bridge
    blank = create_action(actions)
    actions.update(blank['id'], {'version': 1, 'prompt': '  ', 'status': 'active'}, actor='owner')
    item = create_action(actions)
    actions.update(item['id'], {'version': 1, 'status': 'active'}, actor='owner')
    ids = module.sweep()['runs']
    assert len(ids) == 1
    assert actions.get(blank['id'])['status'] == 'active'
    assert actions.get(item['id'])['status'] == 'in_progress'
    first = authenticated_client.post(f'/api/hfl-agent/runs/{ids[0]}/claim', headers=WORKER, json={}).json()
    event(authenticated_client, first, 'failed', {'summary': 'Download failed.'})
    assert actions.get(item['id'])['status'] == 'incomplete'
    current = actions.get(item['id'])
    actions.update(item['id'], {'version': current['version'], 'status': 'active'}, actor='owner')
    assert module.sweep()['runs'] == []  # Configured cadence is durable across ticks.
    with store.connect() as db:
        db.execute("DELETE FROM agent_dispatch_state WHERE key='actions-poll'")
    second = module.sweep()['runs'][0]
    assert second != first['id']
    assert len(store.list('actionable:' + item['id'])) == 2
    assert event(authenticated_client, first, 'progress', {'summary': 'Late result'}).status_code == 409
    assert actions.get(item['id'])['status'] == 'in_progress'


def test_external_action_opt_out_survives_edits_and_scheduler_ticks(bridge):
    module, store, actions = bridge
    item = actions.create({'request_id': str(uuid4()), 'title': 'Save intent',
                           'expected_outcome': 'Review later', 'prompt': 'A complete prompt',
                           'agent_enabled': False}, actor='owner-api')[0]
    actions.update(item['id'], {'version': 1, 'notes': 'Edited', 'status': 'active'}, actor='owner')
    assert module.sweep()['runs'] == []
    assert actions.get(item['id'])['status'] == 'active'
    assert actions.get(item['id'])['agent_enabled'] is False


def test_run_inputs_are_lease_scoped_and_survive_detachment(bridge, authenticated_client):
    module, store, actions = bridge
    item = create_action(actions)
    url = f"/hfl-corpus/agent-bridge/inputs/actionable/{item['id']}"
    assert authenticated_client.post(url, files={'files': ('brief.md', b'Brief')}).status_code == 403
    uploaded = authenticated_client.post(url, headers=owner_headers(), files=[('files', ('brief.md', b'Brief')), ('files', ('data.csv', b'a,b'))])
    assert uploaded.status_code == 200, uploaded.text
    rows = uploaded.json()['attachments']
    assert all(row['group'] == 'uploaded' for row in rows)
    rows = [{k: v for k, v in row.items() if k != 'group'} for row in rows]
    run = start(authenticated_client, item)
    assert run['snapshot']['source']['attachments'] == rows
    download = f"/api/hfl-agent/runs/{run['id']}/inputs/{rows[0]['id']}"
    assert authenticated_client.get(download, headers=WORKER).status_code == 409
    headers = {**WORKER, 'X-Execution-Lease': run['lease_token']}
    assert authenticated_client.get(download, headers=headers).content == b'Brief'
    assert authenticated_client.get(download.rsplit('/', 1)[0] + '/unknown', headers=headers).status_code == 404
    assert authenticated_client.delete(url + '/' + rows[0]['id'], headers=owner_headers()).status_code == 200
    assert len(authenticated_client.get(url).json()['attachments']) == 1
    assert authenticated_client.get(download, headers=headers).content == b'Brief'
    assert store.get(run['id'])['snapshot']['source']['attachments'] == rows


def test_unavailable_inputs_prevent_dispatch_without_stopping_sweep(bridge, monkeypatch):
    from fastapi import HTTPException
    module, store, actions = bridge
    item = create_action(actions)
    actions.update(item['id'], {'version': 1, 'status': 'active'}, actor='owner')
    def unavailable(*args):
        raise HTTPException(502, 'Canonical attachment service unavailable.')
    monkeypatch.setattr(module, 'input_manifest', unavailable)
    result = module.sweep()
    assert result['runs'] == []
    assert actions.get(item['id'])['status'] == 'active'


def test_owner_attachment_proxy_uses_canonical_bearer_and_preserves_bytes(bridge, authenticated_client, monkeypatch):
    import httpx
    from types import SimpleNamespace
    module, store, actions = bridge
    item = create_action(actions)
    original = httpx.Client
    def transport(request):
        assert request.headers['Authorization'] == 'Bearer frontend-test-hfl-api-token'
        response = authenticated_client.request(request.method, request.url.raw_path.decode(), content=request.content,
            headers={'Authorization': request.headers['Authorization'], 'Content-Type': request.headers.get('Content-Type', '')})
        return httpx.Response(response.status_code, content=response.content, headers=response.headers)
    monkeypatch.setattr(module, 'get_settings', lambda: SimpleNamespace(hfl_corpus_api_url='https://canonical.test', hfl_corpus_api_token='frontend-test-hfl-api-token'))
    monkeypatch.setattr(module.httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(transport), **kw))
    monkeypatch.delenv('HFL_TIMELINE_LOCAL_PREVIEW')
    url = f"/hfl-corpus/agent-bridge/inputs/actionable/{item['id']}"
    result = authenticated_client.post(url, headers=owner_headers(), files={'files': ('remote.txt', b'Remote input')})
    assert result.status_code == 200, result.text
    row = result.json()['attachments'][0]
    assert authenticated_client.get(url).json()['attachments'] == [row]
    assert authenticated_client.get(url + '/' + row['id']).content == b'Remote input'
    assert authenticated_client.delete(url + '/' + row['id'], headers=owner_headers()).json()['attachments'] == []


def test_reopened_running_attempt_cannot_complete_new_revision(bridge, authenticated_client):
    module, store, actions = bridge
    item = create_action(actions)
    first = start(authenticated_client, item, auto=True)
    current = actions.get(item['id'])
    actions.update(item['id'], {'version': current['version'], 'status': 'active'}, actor='owner')
    second = module.enqueue('actionable', item['id'], 'reopened', 'owner')
    assert second['id'] != first['id']
    assert store.get(first['id'])['state'] == 'cancelled'
    assert event(authenticated_client, first, 'succeeded', RESULT).status_code == 409


@pytest.mark.parametrize('kind,payload', [('failed', {'summary': 'Failed'}), ('awaiting_input', {'summary': 'Need authorization'}), ('succeeded', {**RESULT, 'complete': False})])
def test_unfulfilled_prompt_becomes_incomplete(bridge, authenticated_client, kind, payload):
    module, store, actions = bridge
    item = create_action(actions)
    run = start(authenticated_client, item, auto=True)
    event(authenticated_client, run, 'plan', {'summary': 'Plan'})
    assert event(authenticated_client, run, kind, payload).status_code == 200
    assert actions.get(item['id'])['status'] == 'incomplete'


def test_agent_board_context_and_additive_associations(bridge, authenticated_client, monkeypatch):
    from workflows.hfl.ideas_store import IdeasStore
    from modules.hfl_corpus import entities
    module, store, actions = bridge
    monkeypatch.setattr(entities, 'current_entries', lambda *args: [])
    monkeypatch.setattr(entities, 'projection', lambda *args: [])
    ideas = IdeasStore(actions)
    boards = [ideas.save_map(dict(request_id=str(uuid4()), name=name, members=[], positions={}))
              for name in ['Selected', 'Relevant', 'Now inactive']]
    item = create_action(actions)
    item = actions.update(item['id'], dict(version=1, board_ids=[boards[0]['id']]), actor='owner')
    linked = ideas.save_idea(dict(request_id=str(uuid4()), title='Supporting idea', body='Full supporting detail', board_ids=[boards[1]['id']]), 'owner')
    run = start(authenticated_client, item, auto=True)
    source = run['snapshot']['source']
    assert source['board_ids'] == [boards[0]['id']]
    relevant = next(b for b in source['available_boards'] if b['id'] == boards[1]['id'])
    assert relevant['members'][0]['id'] == 'idea:' + linked['id']
    assert relevant['members'][0]['body'] == 'Full supporting detail'
    ideas.save_map(dict(version=1, active=False), boards[2]['id'])
    event(authenticated_client, run, 'plan', {'summary': 'Review board context'})
    response = event(authenticated_client, run, 'succeeded', {**RESULT, 'board_ids': [boards[1]['id'], boards[2]['id'], 'removed']})
    assert response.status_code == 200, response.text
    assert actions.get(item['id'])['board_ids'] == sorted([boards[0]['id'], boards[1]['id']])
    assert ideas.map(boards[1]['id'])['edges'] == []


def test_pin_hour_backfill_and_older_gap_notice_are_deduplicated(bridge, monkeypatch):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    module, store, actions = bridge
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 12, 10, tzinfo=ZoneInfo('Asia/Singapore'))
    monkeypatch.setattr(module, 'datetime', Clock)
    pins = module.get_memory_pin_store()
    pins.save_category(category_id=None, name='Daily', color='#f59e0b', instructions='Category context')
    category = pins.snapshot()['categories'][0]
    pins.save_range(range_id=None, category_id=category['id'], start_date='2026-09-01', end_date='2026-09-13', title='Daily review', prompt='Summarize the occurrence day', note='Pin context', execution_hour=12)
    pin = pins.snapshot()['ranges'][0]
    assert pin['agent_enabled']
    occurrences = []
    for _ in range(7):
        run = store.get(module.sweep()['runs'][0])
        occurrences.append(run['snapshot']['occurrence_date'])
        assert run['snapshot']['category_guidance'] == 'Category context'
        store.owner_transition(run['id'], 'cancelled', 'owner', 'Accounted for')
    assert occurrences == [(Clock.now().date() - timedelta(days=n)).isoformat() for n in range(7, 0, -1)]
    assert module.sweep()['runs'] == []  # Today's noon has not arrived.
    assert store.notice_sent(f"older-gap:pin:{pin['id']}:2026-09-01")
    pins.archive_category(category['id'])
    assert module.sweep()['runs'] == []


def test_existing_pin_opt_out_survives_edits(bridge):
    module, store, actions = bridge
    pins = module.get_memory_pin_store()
    pins.save_category(category_id=None, name='Legacy', color='#f59e0b')
    category = pins.snapshot()['categories'][0]
    values = dict(category_id=category['id'], start_date='2026-09-12', end_date='2026-09-12', title='Existing', prompt='Review', note='')
    pins.save_range(range_id=None, **values, agent_enabled=False)
    pin = pins.snapshot()['ranges'][0]
    pins.save_range(range_id=pin['id'], **values)
    assert not pins.snapshot()['ranges'][0]['agent_enabled']
    assert module.sweep()['runs'] == []
    store.subscribe('pin', str(pin['id']), 'daily', True)
    assert pins.snapshot()['ranges'][0]['agent_enabled']


def test_artifacts_require_lease_and_owner_and_render_safe_markdown(bridge, authenticated_client):
    module, store, actions = bridge
    item = create_action(actions)
    run = start(authenticated_client, item, auto=True)
    path = f"/api/hfl-agent/runs/{run['id']}/artifacts/report.md"
    assert authenticated_client.post(path, headers=WORKER, content=b'# Report').status_code == 409
    headers = {**WORKER, 'X-Execution-Lease': run['lease_token']}
    uploaded = authenticated_client.post(path, headers=headers, content=b'# Report\n\n[Docs](https://example.org)\n<script>alert(1)</script>')
    assert uploaded.status_code == 200, uploaded.text
    files = authenticated_client.get('/hfl-corpus/agent-bridge/inputs/actionable/' + item['id']).json()['attachments']
    assert files[0]['group'] == 'generated'
    assert authenticated_client.post(path, headers=headers, content=b'Changed').status_code == 409
    url = uploaded.json()['url']
    preview = authenticated_client.get(url + '?view=true')
    assert '<h1' in preview.text and '<script>' not in preview.text
    assert 'href="https://example.org"' in preview.text
    assert 'attachment' in authenticated_client.get(url).headers['content-disposition']
    event(authenticated_client, run, 'plan', {'summary': 'Create report'})
    event(authenticated_client, run, 'succeeded', {**RESULT, 'summary': f'**Finished** [Report]({url}) <img src=x onerror=alert(1)>'})
    view = authenticated_client.get(f"/hfl-corpus/agent-bridge/sources/actionable/{item['id']}").json()
    assert '<strong>Finished</strong>' in view['runs'][0]['result']['output_html']
    assert 'onerror=' not in view['runs'][0]['result']['output_html']
    assert authenticated_client.post(path, headers=headers, content=b'# Late').status_code == 409
    authenticated_client.cookies.clear()
    assert authenticated_client.get(url).status_code == 401


def test_browser_settings_and_future_dates(bridge, authenticated_client, monkeypatch, tmp_path):
    from datetime import date
    from urllib.parse import urlparse
    playwright = pytest.importorskip('playwright.sync_api')
    module, store, actions = bridge
    monkeypatch.setattr(module.corpus_index, 'documents', lambda: ())
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel='chrome', headless=True)
        except playwright.Error:
            pytest.skip('Installed Chrome is required.')
        page = browser.new_page(viewport={'width': 1200, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def route(request_route):
            req = request_route.request
            url = urlparse(req.url)
            if url.hostname != 'bridge.test':
                request_route.abort()
                return
            response = authenticated_client.request(req.method, url.path + ('?' + url.query if url.query else ''), content=req.post_data,
                headers={key: value for key, value in req.headers.items() if key.lower() in {'content-type', 'x-csrf-token'}})
            request_route.fulfill(status=response.status_code, headers={'content-type': response.headers.get('content-type', 'text/html')}, body=response.content)
        page.route('**/*', route)
        page.goto('https://bridge.test/settings')
        page.get_by_text('Actions polling minutes', exact=False).first.wait_for()
        page.locator('summary[aria-label="Profile menu"]').click()
        assert page.locator('nav[aria-label="Profile menu"] a[href="/settings"]').is_visible()
        page.locator('summary[aria-label="Profile menu"]').click()
        page.screenshot(path=str(tmp_path / 'settings-desktop.png'))
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(tmp_path / 'settings-mobile.png'))
        assert page.locator('body').evaluate('(el) => el.scrollWidth <= window.innerWidth')
        page.set_viewport_size({'width': 1200, 'height': 900})
        page.goto(f'https://bridge.test/hfl-corpus?activity_year={date.today().year + 1}')
        day = page.locator('[data-activity-day][data-future="true"]').first
        day.click()
        ideas = page.locator('[data-activity-menu-ideas]')
        assert ideas.is_disabled()
        assert page.locator('[data-activity-menu-actions]').get_attribute('aria-expanded') == 'true'
        assert page.locator('[data-day-actions]').is_visible()
        page.screenshot(path=str(tmp_path / 'future-actions.png'))
        assert page.locator('#pin-execution-hour option').count() == 12
        assert page.locator('#pin-execution-period option').count() == 2
        page.locator('[data-activity-menu-pin]').click()
        day.click()
        playwright.expect(page.locator('[data-memory-dialog]')).to_be_visible()
        helper = page.locator('[data-pin-schedule-help]')
        playwright.expect(helper).to_contain_text('12:00 AM (Asia/Singapore)')
        page.locator('#pin-execution-hour').select_option('2')
        page.locator('#pin-execution-period').select_option('PM')
        playwright.expect(helper).to_contain_text('2:00 PM (Asia/Singapore)')
        page.locator('#pin-agent-enabled').uncheck()
        playwright.expect(helper).to_contain_text('Daily runs are off')
        assert page.locator('#pin-execution-hour').is_disabled()
        page.locator('#pin-agent-enabled').check()
        page.set_viewport_size({'width':390, 'height':844})
        toggle = page.locator('.pin-schedule-toggle').bounding_box()
        controls = page.locator('.pin-schedule-time').bounding_box()
        assert abs(toggle['y'] - controls['y']) < 2
        assert page.locator('[data-memory-dialog]').evaluate('(el) => el.scrollWidth <= el.clientWidth')
        page.screenshot(path=str(tmp_path / 'pin-schedule-mobile.png'))
        assert errors == []
        browser.close()


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
    actions.update(item['id'], {'version': actions.get(item['id'])['version'], 'prompt': 'A different task'}, actor='owner')
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


def test_review_drafts_wait_for_ready_and_discovery_is_deduplicated(bridge):
    module, store, actions = bridge
    item = create_action(actions)
    assert module.sweep()['runs'] == []
    item = actions.update(item['id'], {'version': item['version'], 'prompt': 'Fully drafted instructions'}, actor='owner')
    with store.connect() as db:
        db.execute("DELETE FROM agent_dispatch_state WHERE key='actions-poll'")
    assert module.sweep()['runs'] == []
    assert actions.get(item['id'])['status'] == 'open'
    actions.update(item['id'], {'version': item['version'], 'status': 'active'}, actor='owner')
    with store.connect() as db:
        db.execute("DELETE FROM agent_dispatch_state WHERE key='actions-poll'")
    first = module.sweep()['runs']
    assert len(first) == 1
    assert module.sweep()['runs'] == []
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
    actions.update(item['id'], {'version': 2, 'prompt': 'Changed'}, actor='owner')
    response = authenticated_client.post(f"/api/hfl-agent/runs/{run['id']}/claim", headers=WORKER, json={})
    assert response.status_code == 409
    assert store.get(run['id'])['state'] == 'cancelled'
    assert actions.get(item['id'])['status'] == 'in_progress'


def test_returning_to_review_prevents_queued_worker_pickup(bridge, authenticated_client):
    module, store, actions = bridge
    item = create_action(actions)
    item = actions.update(item['id'], {'version': item['version'], 'status': 'active'}, actor='owner')
    run = module.enqueue('actionable', item['id'], 'ready-request', 'hermes-schedule')
    current = actions.get(item['id'])
    actions.update(item['id'], {'version': current['version'], 'status': 'open'}, actor='owner')
    response = authenticated_client.post(f"/api/hfl-agent/runs/{run['id']}/claim", headers=WORKER, json={})
    assert response.status_code == 409
    assert store.get(run['id'])['state'] == 'cancelled'
    assert actions.get(item['id'])['status'] == 'open'
    with pytest.raises(ValueError, match='Only Ready'):
        module.enqueue('actionable', item['id'], 'stale-sweep', 'hermes-schedule')


def test_after_period_schedule_runs_once_and_ignores_future_pins(bridge):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    module, store, actions = bridge
    pins = module.get_memory_pin_store()
    pins.save_category(category_id=None, name='Review', color='#f59e0b')
    category = pins.snapshot()['categories'][0]
    today = datetime.now(ZoneInfo('Asia/Singapore')).date()
    for day in (today - timedelta(days=1), today + timedelta(days=1)):
        pins.save_range(range_id=None, category_id=category['id'], start_date=day.isoformat(), end_date=day.isoformat(), title='Review', prompt='Review this period', note='')
    past, future = pins.snapshot()['ranges']
    for pin in (past, future):
        store.subscribe('pin', str(pin['id']), 'after_period', False)
    result = module.sweep()['runs']
    assert len(result) == 1
    assert store.get(result[0])['source_key'] == 'pin:' + str(past['id'])
    store.owner_transition(result[0], 'cancelled', 'owner', 'Keep the receipt')
    assert module.sweep()['runs'] == []
    assert len(store.list()) == 1


def test_corpus_context_excludes_protected_linked_entry(bridge, monkeypatch):
    from types import SimpleNamespace
    module, store, actions = bridge
    entry = SimpleNamespace(text='Entry ID: hfl-secret\nPrivate information', tags=('secrets',), secret=False)
    monkeypatch.setattr(module.corpus_index, 'get', lambda path: SimpleNamespace(entries=[entry]))
    context = module.evidence_context({'kind': 'actionable', 'source': {'source': {'path': 'note.md', 'entry_id': 'hfl-secret'}}})
    assert context['entries'] == []


def test_agent_completion_receipt_is_attributed_correctly(bridge):
    from workflows.hfl.timeline import write_completion
    module, store, actions = bridge
    item = create_action(actions)
    item = actions.update(item['id'], {'version': 1, 'status': 'done', 'completion_note': 'Evidence-backed draft.'}, actor='agent:hermes:' + 'a' * 32 + ':done')
    entries = []
    write_completion(item['id'], item['version'], store=actions, submit=lambda entry, **kwargs: entries.append(entry) or {'delivery': 'persisted'})
    assert 'agent-completion' in entries[0].tags
    assert 'Agent completion: Evidence-backed draft.' in entries[0].what_happened
    assert 'Manual completion' not in entries[0].what_happened


def test_remote_actionable_api_preserves_attribution_and_version_checks(bridge, authenticated_client, monkeypatch):
    import httpx
    from types import SimpleNamespace
    module, store, actions = bridge
    item = create_action(actions)
    original_client = httpx.Client
    def transport(request):
        response = authenticated_client.request(request.method, request.url.raw_path.decode(), content=request.content,
                                                headers={'Authorization': request.headers['Authorization'], 'Content-Type': 'application/json'})
        return httpx.Response(response.status_code, content=response.content)
    monkeypatch.setattr(module, 'get_settings', lambda: SimpleNamespace(hfl_corpus_api_url='https://canonical.test', hfl_corpus_api_token='frontend-test-hfl-api-token'))
    monkeypatch.setattr(module.httpx, 'Client', lambda **kwargs: original_client(transport=httpx.MockTransport(transport), **kwargs))
    monkeypatch.delenv('HFL_TIMELINE_LOCAL_PREVIEW')
    assert module.action_call('GET', '/' + item['id'])['item']['version'] == 1
    actor = 'agent:hermes:' + 'b' * 32 + ':in_progress'
    module.action_call('PATCH', '/' + item['id'], {'version': 1, 'status': 'in_progress', '_agent_actor': actor})
    assert actions.history(item['id'])[0]['actor'] == actor
    with pytest.raises(ValueError, match='changed'):
        module.action_call('PATCH', '/' + item['id'], {'version': 1, 'status': 'in_progress', '_agent_actor': actor})


def test_receipt_failure_retries_from_durable_request(bridge, monkeypatch):
    module, store, actions = bridge
    delivery = module.deliver_pending
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
        page.get_by_role('heading', name='No results yet').wait_for()
        page.screenshot(path=str(tmp_path / 'agent-results-empty.png'))
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(tmp_path / 'agent-results-empty-mobile.png'))
        page.set_viewport_size({'width': 1100, 'height': 850})
        page.get_by_role('button', name='Run now', exact=True).click()
        page.get_by_text('Waiting for an agent to start. You can leave this dialog and check back later.').wait_for()
        run_id = store.list()[0]['id']
        run = authenticated_client.post(f'/api/hfl-agent/runs/{run_id}/claim', headers=WORKER, json={}).json()
        original_scope = run['request_key']
        event(authenticated_client, run, 'awaiting_input', {'summary': 'Choose the report format.', 'blocked_reason': 'input', 'question': 'Which format should I use?', 'complete': False})
        page.get_by_role('button', name='Refresh', exact=True).click()
        page.get_by_role('button', name='Answer and continue').click()
        page.get_by_text('Enter your answer before continuing.').wait_for()
        page.get_by_label('Your reply').fill('Use Markdown and keep the existing evidence.')
        page.screenshot(path=str(tmp_path / 'agent-reply-desktop.png'))
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.locator('dialog').evaluate('(el) => el.scrollWidth <= el.clientWidth')
        page.screenshot(path=str(tmp_path / 'agent-reply-mobile.png'))
        page.get_by_role('button', name='Answer and continue').click()
        page.get_by_text('Waiting for an agent to start. You can leave this dialog and check back later.').wait_for()
        run_id = store.list()[0]['id']
        run = authenticated_client.post(f'/api/hfl-agent/runs/{run_id}/claim', headers=WORKER, json={}).json()
        assert run['snapshot']['operation_scope'] == original_scope
        event(authenticated_client, run, 'failed', {'summary': 'Gmail service unavailable.', 'blocked_reason': 'integration', 'complete': False})
        page.get_by_role('button', name='Refresh', exact=True).click()
        page.get_by_role('heading', name='Blocked by integration', exact=True).wait_for()
        page.get_by_role('button', name='Retry after fix').click()
        page.get_by_text('Waiting for an agent to start. You can leave this dialog and check back later.').wait_for()
        run_id = store.list()[0]['id']
        run = authenticated_client.post(f'/api/hfl-agent/runs/{run_id}/claim', headers=WORKER, json={}).json()
        assert run['snapshot']['operation_scope'] == original_scope
        page.set_viewport_size({'width': 1100, 'height': 850})
        event(authenticated_client, run, 'plan', {'summary': 'Check the expected outcome.'})
        summary = '''# Release report

**Integration verified:** 745 unique bugs, including 245 without a fixVersion.

## Monthly releases

| FixVersion | Release month | Bugs |
| --- | --- | --- |
| R26.08 | August 2026 | 123 |
| R26.09 | September 2026 | 42 |

## Scope and verification

- Reviewed **745 distinct issues** across eight pages.
- Counts reflect version assignments, not necessarily shipped fixes.

Draft ready. <img src=x onerror=alert(1)> is literal text.

### Files

[result.md](/hfl-corpus/agent-bridge/artifacts/sample/result.md?view=true) · [Download](/hfl-corpus/agent-bridge/artifacts/sample/result.md)

[release_counts.csv](/hfl-corpus/agent-bridge/artifacts/sample/release_counts.csv?view=true) · [Download](/hfl-corpus/agent-bridge/artifacts/sample/release_counts.csv)
'''
        event(authenticated_client, run, 'succeeded', {**RESULT, 'summary': summary,
            'evidence': ['actionable:' + item['id'], 'https://example.org/issues/?jql=project%20%3D%20ICON']})
        page.get_by_role('button', name='Refresh', exact=True).click()
        page.get_by_role('heading', name='Completed', exact=True).wait_for()
        report = page.locator('.agent-result-card').first
        assert report.locator('.markdown-body').evaluate('(el) => getComputedStyle(el).whiteSpace') == 'normal'
        assert report.locator('.agent-output-file').count() == 2
        assert report.get_by_role('link', name='Download result.md').get_attribute('href').endswith('/result.md')
        assert report.locator('.agent-output-evidence').get_attribute('open') is None
        report.get_by_text('Sources and evidence · 2', exact=True).click()
        assert report.get_by_role('link', name='example.org/issues/').get_attribute('href') == 'https://example.org/issues/?jql=project%20%3D%20ICON'
        report.get_by_text('Sources and evidence · 2', exact=True).click()
        page.locator('dialog').evaluate('(el) => { el.scrollTop = 0; }')
        page.screenshot(path=str(tmp_path / 'agent-bridge-desktop.png'))
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(tmp_path / 'agent-bridge-mobile.png'))
        assert page.locator('dialog [onerror]').count() == 0
        assert page.locator('dialog').evaluate('(el) => el.scrollWidth <= el.clientWidth')
        page.get_by_role('heading', name='Completed', exact=True).wait_for()
        assert actions.get(item['id'])['status'] == 'done'
        assert errors == []
        browser.close()


def test_execution_settings_frozen_at_enqueue(bridge, authenticated_client):
    from modules.app_settings.store import save_settings
    module, store, actions = bridge
    item = create_action(actions)
    save_settings({'hermes_profile': 'research', 'agent_max_turns': 45})
    run = start(authenticated_client, item)
    save_settings({'hermes_profile': 'default'})
    assert run['snapshot']['execution_settings']['hermes_profile'] == 'research'
    assert run['snapshot']['execution_settings']['agent_max_turns'] == 45


def test_agent_settings_validation(bridge):
    from modules.app_settings.store import save_settings
    for values in ({'hermes_profile': '../escape'}, {'agent_mode': 'unknown'},
                   {'agent_max_turns': 201}, {'agent_timeout_seconds': 0},
                   {'agent_default_recipient': 'bad\naddress@example.org'}):
        with pytest.raises(ValueError):
            save_settings(values)


def test_continue_preserves_context_files_and_operation_scope(bridge, authenticated_client):
    module, store, actions = bridge
    item = create_action(actions)
    first = start(authenticated_client, item)
    upload = authenticated_client.post(f"/api/hfl-agent/runs/{first['id']}/artifacts/report.md",
        headers={**WORKER, 'X-Execution-Lease': first['lease_token']}, content=b'# Original report')
    assert upload.status_code == 200
    stopped = {'summary': 'Report ready; which recipient?', 'blocked_reason': 'input', 'question': 'Who should receive it?', 'complete': False}
    assert event(authenticated_client, first, 'awaiting_input', stopped).status_code == 200
    path = f"/hfl-corpus/agent-bridge/runs/{first['id']}/continue"
    payload = {'request_key': str(uuid4()), 'reply': 'Use owner@example.org.'}
    assert authenticated_client.post(path, json=payload).status_code == 403
    assert authenticated_client.post(path, headers=owner_headers(), json={**payload, 'reply': ''}).status_code == 400
    response = authenticated_client.post(path, headers=owner_headers(), json=payload)
    assert response.status_code == 200, response.text
    second = response.json()
    assert second['snapshot']['source']['prompt'] == first['snapshot']['source']['prompt']
    assert second['snapshot']['operation_scope'] == first['request_key']
    assert second['snapshot']['continuation']['history'][0]['result'] == stopped
    assert second['snapshot']['continuation']['artifacts'][0]['name'] == 'report.md'
    assert actions.get(item['id'])['status'] == 'in_progress'
    assert store.get(first['id'])['state'] == 'cancelled'
    assert authenticated_client.post(path, headers=owner_headers(), json=payload).json()['id'] == second['id']
    assert authenticated_client.post(path, headers=owner_headers(), json={**payload, 'reply': 'Different'}).status_code == 409
    assert authenticated_client.post(path, headers=owner_headers(), json={**payload, 'request_key': str(uuid4())}).status_code == 409
    second = authenticated_client.post(f"/api/hfl-agent/runs/{second['id']}/claim", headers=WORKER, json={}).json()
    file_url = f"/api/hfl-agent/runs/{second['id']}/prior-artifacts/report.md"
    assert authenticated_client.get(file_url, headers=WORKER).status_code == 409
    assert authenticated_client.get(file_url, headers={**WORKER, 'X-Execution-Lease': second['lease_token']}).content == b'# Original report'
    event(authenticated_client, second, 'failed', {'summary': 'Gmail unavailable', 'blocked_reason': 'integration'})
    assert authenticated_client.get(file_url, headers={**WORKER, 'X-Execution-Lease': second['lease_token']}).status_code == 409
    third = authenticated_client.post(f"/hfl-corpus/agent-bridge/runs/{second['id']}/continue",
        headers=owner_headers(), json={'request_key': str(uuid4()), 'reply': ''}).json()
    assert third['snapshot']['operation_scope'] == first['request_key']
    assert len(third['snapshot']['continuation']['history']) == 2
    assert third['snapshot']['continuation']['artifacts'][0]['run_id'] == first['id']


@pytest.mark.parametrize('edit', [None, {'prompt': 'A different task'}, {'matrix': 'Q4'}])
def test_continue_after_agent_priority_update(bridge, authenticated_client, edit):
    module, store, actions = bridge
    item = create_action(actions)
    first = start(authenticated_client, item)
    result = {'summary': 'Analysis ready; which repository?', 'blocked_reason': 'input',
              'question': 'Which repository?', 'complete': False,
              'matrix': 'Q2', 'matrix_confidence': 'high', 'matrix_reason': 'Long-term project.'}
    assert event(authenticated_client, first, 'awaiting_input', result).status_code == 200
    current = actions.get(item['id'])
    assert current['matrix'] == 'Q2'
    if edit:
        actions.update(item['id'], {'version': current['version'], **edit}, actor='owner')
    payload = {'request_key': str(uuid4()), 'reply': 'Use the existing project repository.'}
    path = f"/hfl-corpus/agent-bridge/runs/{first['id']}/continue"
    response = authenticated_client.post(path, headers=owner_headers(), json=payload)
    assert response.status_code == (409 if edit else 200), response.text
    if not edit:
        assert response.json()['snapshot']['source']['matrix'] == 'Q2'
        assert response.json()['snapshot']['continuation']['reply'] == payload['reply']
        assert authenticated_client.post(path, headers=owner_headers(), json=payload).json()['id'] == response.json()['id']


def test_continue_rejects_changed_source_and_invalid_reply(bridge, authenticated_client):
    module, store, actions = bridge
    item = create_action(actions)
    first = start(authenticated_client, item)
    event(authenticated_client, first, 'failed', {'summary': 'Service unavailable'})
    path = f"/hfl-corpus/agent-bridge/runs/{first['id']}/continue"
    for reply in (None, 123, 'x' * 8001):
        assert authenticated_client.post(path, headers=owner_headers(), json={'request_key': str(uuid4()), 'reply': reply}).status_code == 400
    current = actions.get(item['id'])
    actions.update(item['id'], {'version': current['version'], 'prompt': 'A different task'}, actor='owner')
    response = authenticated_client.post(path, headers=owner_headers(), json={'request_key': str(uuid4()), 'reply': 'Continue'})
    assert response.status_code == 409
    assert len(store.list()) == 1


def test_agent_matrix_context_and_result_are_persisted(bridge, authenticated_client):
    module, store, actions = bridge
    item = create_action(actions)
    item = actions.update(item['id'], {'version':1, 'matrix':'Q3', 'matrix_confidence':'low', 'due_date':'2026-09-20'}, actor='owner')
    run = start(authenticated_client, item, auto=True)
    assert run['snapshot']['source']['matrix'] == 'Q3'
    assert run['snapshot']['source']['due_date'] == '2026-09-20'
    event(authenticated_client, run, 'plan', {'summary':'Assess goals and timing'})
    assert event(authenticated_client, run, 'succeeded', {**RESULT, 'matrix':'Q5'}, key='invalid-matrix').status_code == 400
    result = {**RESULT, 'matrix':'Q2', 'matrix_confidence':'high', 'matrix_reason':'Owner instructions establish long-term importance.'}
    assert event(authenticated_client, run, 'succeeded', result).status_code == 200
    saved = actions.get(item['id'])
    assert saved['status'] == 'done'
    assert saved['matrix'] == 'Q2' and saved['matrix_confidence'] == 'high'
    assert actions.history(item['id'])[0]['item']['matrix_reason'] == result['matrix_reason']


def test_sweep_queues_important_actions_before_less_important_urgency(bridge):
    module, store, actions = bridge
    for matrix in ('Q3', 'Q2', 'Q1', 'Q4'):
        item = create_action(actions)
        actions.update(item['id'], {'version':1, 'matrix':matrix, 'status':'active'}, actor='owner')
    runs = module.sweep()['runs']
    assert [store.get(run)['snapshot']['source']['matrix'] for run in runs] == ['Q1','Q2','Q3','Q4']


def test_agent_classification_cannot_overwrite_concurrent_owner_edit(bridge, authenticated_client):
    module, store, actions = bridge
    item = create_action(actions)
    run = start(authenticated_client, item, auto=True)
    current = actions.get(item['id'])
    edited = actions.update(item['id'], {'version':current['version'], 'matrix':'Q4', 'matrix_confidence':'high'}, actor='owner')
    event(authenticated_client, run, 'plan', {'summary':'Review task'})
    response = event(authenticated_client, run, 'succeeded', {**RESULT, 'matrix':'Q1', 'matrix_confidence':'medium', 'matrix_reason':'Agent assessment'})
    assert response.status_code == 200
    assert response.json()['state'] == 'review'
    assert actions.get(item['id'])['matrix'] == 'Q4'
    assert actions.get(item['id'])['version'] == edited['version']


def test_saved_canonical_outcome_appears_without_local_run(bridge, authenticated_client):
    module, store, actions = bridge
    item = create_action(actions)
    summary = '## Report\n\n| Month | Total |\n| --- | --- |\n| Sep | **12** |\n\n<script>alert(1)</script>'
    item = actions.update(item['id'], {'version':item['version'],'status':'done','completion_note':summary}, actor='agent:external')
    actions.update(item['id'], {'version':item['version'],'notes':'Unrelated edit'}, actor='owner')
    result = authenticated_client.get(f"/hfl-corpus/agent-bridge/sources/actionable/{item['id']}").json()
    assert result['runs'] == []
    assert result['action_status'] == 'done'
    assert len(result['outcomes']) == 1
    assert '<table>' in result['outcomes'][0]['output_html']
    assert '<strong>12</strong>' in result['outcomes'][0]['output_html']
    assert '<script>' not in result['outcomes'][0]['output_html']
    history = authenticated_client.get(f"/hfl-corpus/timeline/items/{item['id']}/history").json()
    assert '<table>' in history['history'][0]['item']['completion_note_html']


def test_attachment_previews_are_passive_and_support_word(bridge, authenticated_client):
    import io
    import zipfile
    module, _, _ = bridge
    result=module.input_preview(b'# Heading\n\n<script>bad()</script>', 'brief.md')
    assert b'<h1' in result.body and b'<script>' not in result.body
    assert 'sandbox' in result.headers['content-security-policy']
    assert module.input_preview(b'plain <b>text</b>', 'notes.txt').media_type == 'text/plain'
    doc=io.BytesIO()
    with zipfile.ZipFile(doc,'w') as zipped:
        zipped.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Word preview</w:t></w:r></w:p></w:document>')
    assert module.input_preview(doc.getvalue(),'report.docx').body == b'Word preview'
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as failure:
        module.input_preview(b'<svg onload="alert(1)"></svg>','unsafe.svg')
    assert failure.value.status_code == 415
    item = create_action(bridge[2])
    path = f"/hfl-corpus/agent-bridge/inputs/actionable/{item['id']}"
    uploaded = authenticated_client.post(path, headers=owner_headers(), files=[('files',('brief.md',b'# Preview report','text/markdown'))])
    assert uploaded.status_code == 200
    attachment = uploaded.json()['attachments'][0]
    viewed = authenticated_client.get(path+'/'+attachment['id']+'?view=true')
    assert viewed.status_code == 200
    assert '<h1' in viewed.text and 'Preview report' in viewed.text
