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


@pytest.mark.parametrize('width', [1440, 390])
def test_unread_launcher_detects_closed_panel_updates(fleet, authenticated_client, tmp_path, width):
    pw = pytest.importorskip('playwright.sync_api')
    data = {'items':[{'id':'notification-demo','title':'Review delivery','date':'2026-11-15',
                     'state':'running','answer':'','mock':True}], 'demo_available':False}
    with pw.sync_playwright() as engine:
        browser=engine.chromium.launch(channel='chrome',headless=True)
        try:
            context=browser.new_context(viewport={'width':width,'height':844})
            page=context.new_page()
            errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            def route(r):
                u=urlparse(r.request.url)
                if u.path==URL:r.fulfill(json=data);return
                response=authenticated_client.request(r.request.method,u.path+('?' + u.query if u.query else ''),
                    content=r.request.post_data_buffer,headers={k:v for k,v in r.request.headers.items() if k in {'content-type','x-csrf-token'}})
                r.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','text/html'))
            context.route('https://unread.test/**',route)
            page.clock.install()
            page.goto('https://unread.test/home')
            launch=page.locator('#butler-launch')
            pw.expect(launch).to_have_attribute('data-unread','false')
            data['items'][0].update(state='completed',answer='Your report is ready.')
            page.clock.fast_forward(31000)
            pw.expect(launch).to_have_attribute('data-unread','true')
            pw.expect(page.locator('#butler-panel')).not_to_be_visible()
            pw.expect(launch).to_have_attribute('aria-describedby','butler-unread-status')
            pw.expect(page.locator('#butler-unread-status')).to_have_text('1 unread briefing or agent update')
            assert launch.evaluate("el=>getComputedStyle(el,'::after').backgroundColor")=='rgb(103, 232, 249)'
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(tmp_path/f'butler-unread-{width}.png'))
            launch.click()
            pane=page.get_by_role('tabpanel',name='Briefings',exact=True)
            pw.expect(pane.get_by_text('Your report is ready.',exact=True)).to_be_visible()
            pw.expect(launch).to_have_attribute('data-unread','true')
            pane.get_by_role('button',name='Reviewed',exact=True).click()
            pw.expect(launch).to_have_attribute('data-unread','false')
            review_key='harqis:butler:reviewed:v1:'+USER
            saved=page.evaluate('(key)=>localStorage.getItem(key)',review_key)
            page.reload()
            pw.expect(launch).to_have_attribute('data-unread','false')
            launch.click()
            pane.get_by_label('Show reviewed').check()
            pane.get_by_role('button',name='Mark unread',exact=True).click()
            pw.expect(launch).to_have_attribute('data-unread','true')
            # A review in another tab updates the launcher without a new fetch.
            other=context.new_page()
            other.goto('https://unread.test/home')
            other.evaluate('([key,value])=>localStorage.setItem(key,value)',[review_key,saved])
            pw.expect(launch).to_have_attribute('data-unread','false')
            assert not errors,errors
        finally:
            browser.close()


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
            pane.get_by_role('heading', name='No unread updates').wait_for()
            assert not page.locator('#butler-form').is_visible()
            pane.get_by_role('button', name='Load sample briefings').click()
            pw.expect(pane.locator('.butler-briefing-card')).to_have_count(5)
            assert pane.get_by_text('Mock', exact=True).count() == 5
            assert pane.get_by_text('Completed', exact=True).count() == 2
            assert pane.get_by_text('Failed', exact=True).is_visible()
            pane.get_by_role('button', name='Reviewed', exact=True).first.click()
            pw.expect(pane.locator('.butler-briefing-card')).to_have_count(4)
            pane.get_by_label('Show reviewed').check()
            pw.expect(pane.locator('.butler-briefing-card')).to_have_count(5)
            pane.get_by_role('button', name='Mark unread', exact=True).click()
            pane.get_by_label('Show reviewed').uncheck()
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
