"""Canonical status, attribution and orphan visibility across Fleet and Kanban."""
from frontend.tests.test_agent_fleet import fleet, post
from frontend.tests.test_hfl_agent_bridge import bridge


def test_canonical_status_assignment_orphans_and_provenance():
    from modules.agents.corpus_projection import extend
    agents = [{'id': identity} for identity in ['butler', 'sharing', 'ada', 'leo']]
    snapshot = {'actions': [{'id': 'a', 'title': 'Action', 'status': 'done'},
                            {'id': 'orphan', 'title': 'Manual action', 'status': 'open'}],
                'ideas': [{'id': 'i', 'title': 'Generated idea', 'status': 'suggested'},
                          {'id': 'm', 'title': 'Manual idea', 'status': 'dismissed', 'origin': 'manual'}]}
    entries = [{'id': 'e', 'source': 'agents-activity', 'text': '{"agent_id":"ada"}', 'path':'test.md'},
               {'id': 's', 'source': 'sharing-audit', 'text': 'Sanitized question and answer', 'path':'test.md'},
               {'id': 'unattributed', 'source': 'manual', 'text': 'ada mentioned here', 'path':'test.md'}]
    nodes, edges = {}, {}
    extend(nodes, edges, agents, {'card:a': {'agent_id':'leo'}}, snapshot, entries)
    assert nodes['action:a']['agent_ids'] == ['leo']
    assert nodes['action:a']['color'] == '#4ade80'
    assert nodes['action:orphan']['agent_ids'] == []
    assert nodes['idea:i']['agent_ids'] == ['butler']
    assert nodes['idea:m']['agent_ids'] == [] and nodes['idea:m']['color'] == '#94a3b8'
    assert nodes['entry:e']['agent_ids'] == ['ada']
    assert nodes['entry:s']['agent_ids'] == ['sharing']
    assert 'entry:unattributed' not in nodes
    snapshot['links']=[{'source':'agent:ada','target':'idea:m','relation':'supports'}]
    extend(nodes, edges, agents, {'card:a': {'agent_id':'ada'}}, snapshot, entries)
    assert nodes['action:a']['agent_ids'] == ['ada']
    assert nodes['idea:m']['agent_ids'] == ['ada']
    assert ('agent:ada','idea:m','supports') in edges


def test_managed_sharing_cannot_launch_another_worker(fleet, authenticated_client):
    fleet.initialize()
    result=post(authenticated_client, '/items/sharing/prepare', {})
    assert result.status_code == 422


def test_briefing_markdown_is_sanitized_and_legacy_is_preserved(fleet):
    import json
    from modules.agents import briefings
    fleet.initialize()
    with fleet.store().connect() as db:
        db.execute('INSERT INTO fleet_briefing_deliveries VALUES (?,?,?,?)',
                   ('owner','mock','2026-11-14',json.dumps({'mock':True,'state':'completed','answer':'## Heading\n\n- Item\n\n<script>alert(1)</script>'})))
    html=briefings.history('owner')['items'][0]['answer_html']
    assert '<h2>Heading</h2>' in html and '<li>Item</li>' in html
    assert '<script' not in html
    assert 'Markdown' in briefings.PROMPT


def test_assignment_thumbnails_follow_configuration(fleet, bridge, authenticated_client):
    from modules.hfl_corpus.action_agents import store
    fleet.initialize()
    store().configure('card:demo-action', {'agent_id':'butler'})
    response=authenticated_client.get('/hfl-corpus/agent-bridge/assignments')
    assert response.status_code == 200
    assert response.json()['items']['demo-action'][0]['name'] == 'HARQIS Butler'
    store().configure('card:demo-action', {'agent_id':''})
    assert 'demo-action' not in authenticated_client.get('/hfl-corpus/agent-bridge/assignments').json()['items']


def test_fleet_inline_intent_browser(fleet, bridge, authenticated_client):
    import pytest
    from urllib.parse import urlparse
    from uuid import uuid4
    pw=pytest.importorskip('playwright.sync_api')
    from modules.hfl_corpus.action_agents import store
    from modules.agents import briefings
    item=bridge[2].create({'request_id':str(uuid4()),'title':'Review fleet integration'},actor='owner')[0]
    store().configure('card:'+item['id'],{'agent_id':'butler'})
    fleet.initialize()
    briefings.seed_demo('frontend-test-user')
    errors=[]
    with pw.sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror',lambda error:errors.append(str(error)))
        def route(r):
            u=urlparse(r.request.url)
            response=authenticated_client.request(r.request.method,u.path+('?' + u.query if u.query else ''),content=r.request.post_data_buffer,
                headers={k:v for k,v in r.request.headers.items() if k in {'content-type','x-csrf-token'}})
            r.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','text/html'))
        page.route('https://fleet.test/**',route)
        try:
            page.goto('https://fleet.test/agents?agent=butler')
            page.locator('.fleet-output-list button').filter(has_text=item['title']).click()
            controls=page.locator('.fleet-intent-controls')
            page.get_by_role('button',name='Fullscreen',exact=True).click()
            controls.get_by_role('button',name='Edit',exact=True).click()
            pw.expect(page.locator('#followup-editor')).to_be_visible()
            assert not page.locator('#followup-editor').evaluate('el=>el.inert')
            assert '/agents' in page.url
            page.keyboard.press('Escape')
            page.get_by_role('button',name='Exit fullscreen',exact=True).click()
            controls.get_by_role('button',name='Done',exact=True).click()
            pw.expect(page.locator('.fleet-inspector>.fleet-badge')).to_have_text('Done')
            page.get_by_role('link',name='Show Kanban',exact=True).click()
            card=page.locator('[data-board-lanes] [data-followup-id="'+item['id']+'"]')
            pw.expect(card).to_be_visible()
            assert '/hfl-corpus/actions' in page.url
            assert page.locator('.fleet-toolbar').count()==0
            pw.expect(page.locator('#brain-page-loading')).to_be_hidden()
            assert not page.locator('#kanban-surface').evaluate('el=>el.inert')
            assert card.locator('.action-agent-thumbnails .agent-avatar').count()==1
            card.get_by_role('button',name='History',exact=True).click()
            pw.expect(page.locator('#followup-history')).to_be_visible()
            page.keyboard.press('Escape')
            # Space transitions replace the document: old assignment timers/listeners
            # must stop before the new page installs its own polling lifecycle.
            page.clock.install()
            assignment_requests = []
            page.on('request', lambda request: assignment_requests.append(request.url)
                    if '/agent-bridge/assignments' in request.url else None)
            page.evaluate("window.dispatchEvent(new Event('hfl:view-replacing'))")
            page.clock.fast_forward(45000)
            page.evaluate("window.dispatchEvent(new Event('hfl:agent-updated'))")
            assert assignment_requests == []
            page.get_by_role('link',name='Back to Second Brain fleet',exact=True).click()
            pw.expect(page.locator('.fleet-inspector')).to_be_visible()
            page.locator('.fleet-create summary').click()
            page.locator('.fleet-create').get_by_role('button',name='Idea',exact=True).click()
            pw.expect(page.get_by_role('dialog',name='New idea',exact=True)).to_be_visible()
            assert not errors,errors
        finally:
            browser.close()
