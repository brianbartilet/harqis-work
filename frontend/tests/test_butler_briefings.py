"""Scheduled results are delivered separately from gateway conversation history."""
import json
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from test_agent_fleet import fleet  # noqa: F401
from test_hfl_agent_bridge import bridge, owner_headers, event, RESULT, WORKER  # noqa: F401

USER = 'frontend-test-user'
URL = '/agents/api/butler/briefings'


def test_scheduled_worker_result_is_visible_once_and_owner_scoped(fleet, bridge, authenticated_client):
    from modules.agents import briefings
    client = authenticated_client
    fleet.initialize()
    briefings.save(USER, {**briefings.DEFAULT, 'cadence': 'daily', 'hour': 0, 'timezone': 'UTC'})
    instant = datetime(2026, 11, 13, 10, tzinfo=timezone.utc)
    briefings.sweep(instant)
    first = client.get(URL).json()['items']
    assert len(first) == 1 and first[0]['state'] == 'pending'
    assert first[0]['date'] == '2026-11-13'
    run = client.post('/api/hfl-agent/runs/' + first[0]['run_id'] + '/claim', headers=WORKER, json={}).json()
    assert client.get(URL).json()['items'][0]['state'] == 'running'
    assert event(client, run, 'plan', {'summary': 'Review recent activity without writes.'}).status_code == 200
    result = event(client, run, 'succeeded', {**RESULT, 'summary': 'Your scheduled briefing is ready.'})
    assert result.status_code == 200, result.text
    briefings.sweep(instant)
    items = client.get(URL).json()['items']
    assert len(items) == 1 and items[0]['state'] == 'completed'
    assert items[0]['answer'] == 'Your scheduled briefing is ready.'
    assert briefings.history('different-owner')['items'] == []
    with fleet.store().connect() as db:
        assert db.execute('SELECT count(*) FROM fleet_assistant').fetchone()[0] == 0
    assert client.get(URL).json()['items'] == items


def test_legacy_recovery_requires_exact_scheduler_identity(fleet):
    from modules.agents import briefings
    day = '2026-11-13'
    key = briefings.occurrence_key(USER, day)
    with fleet.store().connect() as db:
        for identity in (key, str(uuid4())):
            db.execute('INSERT INTO fleet_chat(user,request_id,message,created) VALUES (?,?,?,?)',
                       (USER, identity, briefings.PROMPT, '2026-11-12T23:00:00+00:00'))
    items = briefings.history(USER)['items']
    assert [item['id'] for item in items] == [key]
    assert items[0]['date'] == day
    assert briefings.history(USER)['items'] == items


def test_samples_are_preview_only_csrf_protected_and_never_dispatch(fleet, authenticated_client, monkeypatch):
    from modules.agents import briefings, butler
    monkeypatch.setattr(butler, 'send', lambda *args: pytest.fail('Samples must not dispatch'))
    client = authenticated_client
    assert client.post(URL + '/demo').status_code == 403
    assert client.post(URL + '/demo', headers=owner_headers()).status_code == 200
    items = client.get(URL).json()['items']
    assert len(items) == 5 and all(item['mock'] for item in items)
    assert {item['state'] for item in items} == {'pending', 'running', 'completed', 'failed'}
    assert client.post(URL + '/demo', headers=owner_headers()).json()['items'] == items
    assert briefings.read(USER)['cadence'] == 'off'
    with fleet.store().connect() as db:
        assert db.execute('SELECT count(*) FROM fleet_chat').fetchone()[0] == 0
    monkeypatch.setenv('HFL_TIMELINE_LOCAL_PREVIEW', '0')
    assert client.post(URL + '/demo', headers=owner_headers()).status_code == 404
    assert client.get(URL).json() == {'items': [], 'demo_available': False}
    client.cookies.clear()
    assert client.get(URL).status_code == 401


@pytest.mark.parametrize('width,height', [(1440, 1000), (390, 844)])
def test_briefings_browser_without_gateway(fleet, authenticated_client, tmp_path, width, height):
    from modules.agents import briefings
    pw = pytest.importorskip('playwright.sync_api')
    client = authenticated_client
    fleet.initialize()
    with pw.sync_playwright() as engine:
        browser = engine.chromium.launch(channel='chrome', headless=True)
        try:
            page = browser.new_page(viewport={'width': width, 'height': height})
            errors, requests = [], []
            page.on('pageerror', lambda e: errors.append(str(e)))
            def route(r):
                u = urlparse(r.request.url)
                requests.append((r.request.method, u.path))
                response = client.request(r.request.method, u.path + ('?' + u.query if u.query else ''),
                                          content=r.request.post_data_buffer,
                                          headers={k:v for k,v in r.request.headers.items() if k in {'content-type','x-csrf-token'}})
                r.fulfill(status=response.status_code, body=response.content,
                          content_type=response.headers.get('content-type', 'text/html'))
            page.route('https://briefings.test/**', route)
            page.goto('https://briefings.test/home')
            page.click('#butler-launch')
            for label in ('Briefings', 'Conversations', 'Briefing settings'):
                icon = page.get_by_role('tab', name=label, exact=True)
                assert icon.get_attribute('title') == label
                assert icon.locator('svg').count() == 1
                assert icon.inner_text() == ''
            pw.expect(page.get_by_role('tab', name='Briefings', exact=True)).to_have_attribute('aria-selected', 'true')
            pane = page.get_by_role('tabpanel', name='Briefings', exact=True)
            pane.get_by_role('heading', name='No briefings yet').wait_for()
            assert not page.locator('#butler-form').is_visible()
            pane.get_by_role('button', name='Load sample briefings').click()
            pw.expect(pane.locator('.butler-briefing-card')).to_have_count(5)
            assert pane.get_by_text('Mock', exact=True).count() == 5
            assert pane.get_by_text('Completed', exact=True).count() == 2
            assert pane.get_by_text('Failed', exact=True).is_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(tmp_path / f'briefings-{width}.png'))
            # Briefings opens by default after reload, with no gateway submission.
            page.reload()
            page.click('#butler-launch')
            pw.expect(pane.locator('.butler-briefing-card')).to_have_count(5)
            assert not any(method == 'POST' and '/assistant/conversations' in path for method, path in requests)
            assert briefings.read(USER)['cadence'] == 'off'
            # Follow a real isolated scheduler/worker occurrence through polling in this panel.
            briefings.save(USER, {**briefings.DEFAULT, 'cadence': 'daily', 'hour': 0, 'timezone': 'UTC'})
            instant = datetime(2026, 11, 14, 10, tzinfo=timezone.utc)
            briefings.sweep(instant)
            page.get_by_role('button', name='Refresh briefings', exact=True).click()
            pw.expect(pane.locator('.butler-briefing-card')).to_have_count(6)
            actual = next(item for item in briefings.history(USER)['items'] if not item['mock'])
            run = client.post('/api/hfl-agent/runs/' + actual['run_id'] + '/claim', headers=WORKER, json={}).json()
            assert event(client, run, 'plan', {'summary': 'Read the isolated fixture activity.'}).status_code == 200
            assert event(client, run, 'succeeded', {**RESULT, 'summary': 'Delivered by the scheduled worker.'}).status_code == 200
            pane.get_by_text('Delivered by the scheduled worker.', exact=True).wait_for()
            briefings.sweep(instant)
            page.get_by_role('button', name='Refresh briefings', exact=True).click()
            pw.expect(pane.locator('.butler-briefing-card')).to_have_count(6)
            page.get_by_role('tab', name='Briefings', exact=True).focus()
            page.keyboard.press('ArrowRight')
            pw.expect(page.get_by_role('tab', name='Conversations')).to_have_attribute('aria-selected', 'true')
            page.keyboard.press('Escape')
            assert page.locator('#butler-launch').evaluate('(el)=>el===document.activeElement')
            page.click('#butler-launch')
            page.get_by_role('tab', name='Briefing settings', exact=True).click()
            page.get_by_label('Timezone', exact=True).click()
            pw.expect(page.locator('#butler-panel')).to_be_visible()
            page.mouse.click(4, 100)
            pw.expect(page.locator('#butler-panel')).to_be_hidden()
            pw.expect(page.locator('#butler-launch')).to_have_attribute('aria-expanded', 'false')
            page.click('#butler-launch')
            pw.expect(page.locator('#butler-panel')).to_be_visible()
            assert not errors, errors
        finally:
            browser.close()
