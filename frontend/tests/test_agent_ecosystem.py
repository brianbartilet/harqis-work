"""Recorded provenance, safe mocks and graph workspace interactions."""
from pathlib import Path
from urllib.parse import urlparse

import pytest
import json
from frontend.tests.test_agent_fleet import fleet, post
from frontend.tests.test_hfl_agent_bridge import bridge


def test_mock_seed_is_scoped_idempotent_and_non_executable(fleet, authenticated_client, monkeypatch):
    from modules.agents import ecosystem, projection
    user = 'frontend-test-user'
    assert post(authenticated_client, '/demo', {}).status_code == 200
    first = ecosystem.graph(user)
    assert len([a for a in first['agents'] if a.get('mock')]) == 6
    assert len([n for n in first['nodes'] if n.get('mock') and n['kind'] != 'agent']) == 20
    post(authenticated_client, '/demo', {})
    assert len(ecosystem.graph(user)['nodes']) == len(first['nodes'])
    assert not any(a.get('mock') for a in projection.listing('other-owner'))
    agent = next(a for a in first['agents'] if a.get('mock') and a['runtime'] == 'hermes')
    with pytest.raises(ValueError, match='Mock agents'):
        fleet.execution(agent['id'])
    assert post(authenticated_client, '/assistant/primary', {'agent_id': agent['id'], 'version': 0}).status_code == 422
    assert any(e['relation'] == 'returns artifact' for e in first['edges'])
    monkeypatch.setenv('HFL_TIMELINE_LOCAL_PREVIEW', '0')
    assert post(authenticated_client, '/demo', {}).status_code == 403
    assert not any(n.get('mock') for n in ecosystem.graph(user)['nodes'])


def test_connector_classifications_and_name_updates(fleet, authenticated_client):
    for runtime, classification in [('codex','coding'),('claude','coding'),('chatgpt','general'),('n8n','workflows'),('grokbot','workflows')]:
        response = post(authenticated_client, '/items', {'runtime': runtime, 'name': 'Ada ' + runtime})
        assert response.status_code == 200, response.text
        item = response.json()['item']
        assert item['classification'] == classification
        assert post(authenticated_client, '/items/'+item['id'], {'version': 1, 'name': 'Human name'}).status_code == 200
        assert post(authenticated_client, '/items/'+item['id'], {'version': 2, 'runtime':'hermes'}).status_code == 422


def test_observation_provenance_dedup_and_url_boundary(fleet, authenticated_client):
    from modules.agents import ecosystem
    client = authenticated_client
    fleet.initialize()
    raw = {'id':'celery-task-123', 'agent_id':'butler', 'source':'celery', 'kind':'task', 'label':'Calendar complete',
           'summary':'Collected 12 events', 'url':'javascript:alert(1)'}
    one = post(client, '/observations', raw)
    assert one.status_code == 200 and one.json()['url'] == ''
    two = post(client, '/observations', {**raw,'summary':'Collected 13 events'})
    assert one.json()['id'] == two.json()['id']
    assert post(client, '/observations', {**raw,'agent_id':'default'}).status_code == 409
    assert post(client, '/observations', {**raw,'id':'bad','agent_id':'missing'}).status_code == 404
    child = post(client, '/observations', {'id':'child-1','agent_id':'butler','source':'hermes','kind':'subagent','label':'Scout'}).json()
    artifact = post(client, '/observations', {'id':'report-1','agent_id':'butler','source':'hermes','kind':'file','label':'Report', 'delegation_id':child['id']})
    assert artifact.status_code == 200
    graph = ecosystem.graph('frontend-test-user')
    assert any(e['source'] == child['id'] and e['target'] == artifact.json()['id'] for e in graph['edges'])
    assert not any(n['id'] == child['id'] for n in ecosystem.graph('other-owner')['nodes'])
    assert len({n['id'] for n in graph['nodes']}) == len(graph['nodes'])
    ids = {n['id'] for n in graph['nodes']}
    assert all(e['source'] in ids and e['target'] in ids for e in graph['edges'])


def test_primary_branding_and_mock_context_exclusion(fleet, authenticated_client):
    from modules.agents.assistant import page_context
    fleet.initialize()
    assert fleet.store().get('butler')['name'] == 'HARQIS Butler'
    assert fleet.store().get('butler')['color'] == '#e9c96c'
    post(authenticated_client, '/demo', {})
    context = page_context({'version':1,'path':'/agents'}, 'frontend-test-user')
    assert not any('Simulated' in str(n) or 'Milo' in str(n) for n in context['agent_activity'])
    assert 'HARQIS Butler' in authenticated_client.get('/agents').text


@pytest.mark.parametrize('width,height', [(1440,1000),(390,844)])
def test_ecosystem_browser(fleet, authenticated_client, tmp_path, width, height):
    playwright = pytest.importorskip('playwright.sync_api')
    client = authenticated_client
    post(client, '/demo', {})
    with playwright.sync_playwright() as engine:
        browser = engine.chromium.launch(channel='chrome', headless=True)
        try:
            page = browser.new_page(viewport={'width':width,'height':height})
            errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            def route(r):
                u=urlparse(r.request.url)
                response=client.request(r.request.method,u.path+('?' + u.query if u.query else ''),content=r.request.post_data_buffer,
                    headers={k:v for k,v in r.request.headers.items() if k in {'content-type','x-csrf-token'}})
                r.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','text/html'))
            page.route('https://fleet.test/**',route)
            ada=next(a for a in client.get('/agents/api/graph').json()['agents'] if a['name']=='Ada · Senior developer')
            page.goto('https://fleet.test/agents?agent='+ada['id'])
            page.locator('.fleet-layout-loading').wait_for(state='hidden')
            inspector=page.locator('.fleet-inspector')
            playwright.expect(inspector.get_by_role('heading',name=ada['name'],exact=True)).to_be_visible()
            inspector.get_by_role('button',name='Milo · Test specialist',exact=False).click()
            playwright.expect(inspector.get_by_role('heading',name='Milo · Test specialist',exact=True)).to_be_visible()
            assert page.get_by_text('returns artifact',exact=True).is_visible()
            page.get_by_role('button',name='All agent work',exact=True).click()
            playwright.expect(page.get_by_role('complementary',name='Agent work')).to_be_visible()
            assert page.locator('.fleet-hud-panel').count()==0
            page.goto('https://fleet.test/agents?agent=butler')
            page.locator('.fleet-layout-loading').wait_for(state='hidden')
            # Persist actual pointer dragging through the canvas, not an overlay button.
            if width>900:
                page.wait_for_function("JSON.parse(localStorage.getItem('harqis:fleet:graph:v2:frontend-test-user')).positions?.['agent:butler']")
                page.evaluate("""() => {
                  const ctx=document.querySelector('.fleet-map canvas').getContext('2d'),arc=ctx.arc,stroke=ctx.stroke;
                  let last;
                  ctx.arc=function(x,y,r,...rest){last={x,y,r};return arc.call(this,x,y,r,...rest);};
                  ctx.stroke=function(...args){if(this.strokeStyle==='#e9c96c'&&last?.r>20)window.fleetPaint=last;return stroke.apply(this,args);};
                }""")
                page.get_by_role('button',name='Animation',exact=True).click()
                page.get_by_role('region',name='Animation modes').get_by_role('button',name='Breathing',exact=True).click()
                page.keyboard.press('Escape')
                page.wait_for_function('window.fleetPaint')
                page.get_by_role('button',name='Animation',exact=True).click()
                page.get_by_role('region',name='Animation modes').get_by_role('button',name='Off',exact=True).click()
                page.keyboard.press('Escape')
                page.wait_for_timeout(400)
                point=page.evaluate("""() => {
                  const p=window.fleetPaint;
                  const canvas=document.querySelector('.fleet-map canvas'),r=canvas.getBoundingClientRect(),z=canvas.__zoom;
                  return {x:r.x+z.x+p.x*z.k,y:r.y+z.y+p.y*z.k,original:p};
                }""")
                page.mouse.move(point['x'],point['y'])
                page.wait_for_timeout(500)
                assert page.locator('.fleet-map').evaluate('(e)=>getComputedStyle(e).cursor') == 'pointer', {'point':point,'hit':page.evaluate('([x,y])=>document.elementFromPoint(x,y)?.outerHTML.slice(0,500)',[point['x'],point['y']])}
                before_drag=page.evaluate("JSON.parse(localStorage.getItem('harqis:fleet:graph:v2:frontend-test-user')).positions")
                page.mouse.down()
                page.mouse.move(point['x']+60,point['y']+40,steps=15)
                page.mouse.up()
                page.wait_for_function("([x,y]) => {const p=JSON.parse(localStorage.getItem('harqis:fleet:graph:v2:frontend-test-user')).positions['agent:butler'];return Math.hypot(p.x-x,p.y-y)>10;}",arg=[point['original']['x'],point['original']['y']])
                page.wait_for_function("""before => {
                  const positions=JSON.parse(localStorage.getItem('harqis:fleet:graph:v2:frontend-test-user')).positions;
                  return Object.entries(positions).some(([id,p])=>id!=='agent:butler'&&before[id]&&Math.hypot(p.x-before[id].x,p.y-before[id].y)>1);
                }""",arg=before_drag)
                assert page.evaluate("JSON.parse(localStorage.getItem('harqis:fleet:graph:v2:frontend-test-user')).positions['agent:butler'].manual")
            page.get_by_role('button',name='Fullscreen',exact=True).click()
            playwright.expect(page.locator('.fleet-toolbar')).to_be_visible()
            playwright.expect(inspector).to_be_visible()
            page.get_by_role('button',name='All agent work',exact=True).click()
            playwright.expect(inspector).not_to_be_visible()
            playwright.expect(page.get_by_role('complementary',name='Agent work')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(tmp_path/f'fleet-work-fullscreen-{width}.png'))
            page.keyboard.press('Escape')
            playwright.expect(page.get_by_role('button',name='Fullscreen',exact=True)).to_be_focused()
            assert not errors,errors
        finally:
            browser.close()


def test_hud_catalogue_survives_feed_failure(fleet, monkeypatch):
    from modules.agents import ecosystem
    from modules.second_brain import service, hud

    def unavailable():
        raise RuntimeError('Feed temporarily unavailable')

    monkeypatch.setattr(service, 'get_second_brain_store', unavailable)
    monkeypatch.setattr(hud, 'inventory', lambda: [
        {'operation_id': 'calendar', 'label': 'Calendar', 'source_task': 'hud.calendar'},
    ])
    graph = ecosystem.graph('frontend-test-user')
    assert any(n['id'] == 'hud:calendar' and n['kind'] == 'hud' for n in graph['nodes'])
    assert any(e['target'] == 'hud:calendar' and e['relation'] == 'monitors' for e in graph['edges'])
    assert any('feed unavailable' in warning for warning in graph['warnings'])


def test_bounded_graph_keeps_hud_navigation(fleet, authenticated_client, monkeypatch):
    from modules.agents import ecosystem
    nodes = [{'id': 'agent:butler', 'kind': 'agent'}, {'id': 'hud:calendar', 'kind': 'hud'}]
    nodes += [{'id': 'action:'+str(i), 'kind': 'action'} for i in range(120)]
    edge = {'source': 'agent:butler', 'target': 'hud:calendar', 'relation': 'monitors'}
    monkeypatch.setattr(ecosystem, 'graph', lambda user: {
        'nodes': nodes, 'edges': [edge], 'coverage': {}, 'warnings': [],
    })
    response = authenticated_client.get('/agents/api/graph?node_limit=100')
    assert response.status_code == 200
    result = response.json()
    assert len(result['nodes']) == 100
    assert any(n['id'] == 'hud:calendar' for n in result['nodes'])
    assert edge in result['edges']
    assert result['coverage']['graph']['has_more']
