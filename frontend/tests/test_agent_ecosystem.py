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
    from modules.second_brain import hud as shared_hud, agent_hud
    from modules.hfl_corpus import workspace_views as ws
    from modules.hfl_shares.security import make_csrf_token
    hud_space=ws.save(ws.WorkspaceWrite(name='HUD Work',state=ws.WorkspaceState()))
    hud_headers={'X-CSRF-Token':make_csrf_token('frontend-test-user')}
    widgets=[shared_hud.Widget(id='radar',operation='hud.hud_radar.show_daily_radar',accent='#f97316',size='2x2').model_dump(),shared_hud.Widget(id='context',operation='context',size='1x2').model_dump(),shared_hud.Widget(id='monitoring',operation='monitoring',size='1x1').model_dump()]
    seeded=client.put('/second-brain/hud/layout',json={'revision':shared_hud.layout()['revision'],'widgets':widgets,'agent_panel_expanded':False},headers=hud_headers)
    assert seeded.status_code==200
    from modules.hfl_corpus.graph_views import connection
    with connection() as db:
        agent_hud.schema(db)
        db.execute('DELETE FROM agent_hud_layout')
    with playwright.sync_playwright() as engine:
        browser = engine.chromium.launch(channel='chrome', headless=True)
        try:
            page = browser.new_page(viewport={'width':width,'height':height})
            errors=[]
            page.on('pageerror', lambda e:errors.append(str(e)))
            workspace = {'views':[{'id':'work','name':'Work','color':'#67e8f9','schedule':[{'days':[0],'start':'09:00','end':'18:00'}]},hud_space],'preferences':{'dynamic':False,'manual':[],'revision':0},'active':[]}
            def route(r):
                u=urlparse(r.request.url)
                if u.path in {'/second-brain/hud/data','/agents/hud/data'}:
                    r.fulfill(json={'items':{'hud.hud_radar.show_daily_radar':[{'id':'radar','details':'Captured HUD output','status':'fresh','source_at':'2026-11-09T09:00:00Z'}]},'context':[],'source_error':'','spaces':{'views':[hud_space],'active':[hud_space['id']]},'layout':agent_hud.layout() if u.path=='/agents/hud/data' else shared_hud.layout()});return
                if u.path=='/hfl-corpus/workspace-views':
                    r.fulfill(json=workspace);return
                if u.path=='/hfl-corpus/view-preferences':
                    workspace['preferences'].update(json.loads(r.request.post_data))
                    workspace['active']=['work'] if workspace['preferences']['dynamic'] else workspace['preferences']['manual']
                    r.fulfill(json=workspace);return
                response=client.request(r.request.method,u.path+('?' + u.query if u.query else ''),content=r.request.post_data_buffer,
                    headers={k:v for k,v in r.request.headers.items() if k in {'content-type','x-csrf-token'}})
                r.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','text/html'))
            page.route('https://fleet.test/**',route)
            ada=next(a for a in client.get('/agents/api/graph').json()['agents'] if a['name']=='Ada · Senior developer')
            page.goto('https://fleet.test/agents?agent='+ada['id'])
            page.get_by_role('complementary',name='Ada · Senior developer HUD feed').wait_for()
            page.goto('https://fleet.test/agents')
            initial_hud=page.get_by_role('complementary',name='HARQIS Butler HUD feed')
            initial_hud.wait_for()
            # HUD dialogs stay centered independently of the narrow feed panel.
            add_button=initial_hud.get_by_role('button',name='Add HUD items',exact=True)
            add_button.click()
            catalog=page.get_by_role('dialog',name='Add a widget',exact=True)
            catalog.wait_for()
            box=catalog.bounding_box()
            assert abs(box['x']+box['width']/2-width/2)<2
            assert abs(box['y']+box['height']/2-height/2)<2
            search=catalog.get_by_role('searchbox',name='Search widgets')
            search.fill('no-such-widget-xyz')
            assert catalog.get_by_text('No widgets match this search.').is_visible()
            search.fill('Context feed')
            assert catalog.get_by_role('button',name='Added',exact=True).is_disabled()
            search.fill('')
            page.screenshot(path=str(tmp_path/f'hud-catalog-{width}.png'))
            page.keyboard.press('Escape')
            assert add_button.evaluate('(el)=>el===document.activeElement')
            initial_hud.get_by_role('button',name='Build new HUD with agent',exact=True).click()
            builder=page.get_by_role('dialog',name='Build a HUD widget',exact=True)
            box=builder.bounding_box()
            assert abs(box['x']+box['width']/2-width/2)<2
            assert abs(box['y']+box['height']/2-height/2)<2
            assert builder.get_by_placeholder('Weekly delivery pulse').is_visible()
            page.screenshot(path=str(tmp_path/f'hud-builder-{width}.png'))
            builder.get_by_role('button',name='Close',exact=True).click()
            assert initial_hud.get_attribute('data-expanded')=='false'
            assert initial_hud.locator('.fleet-hud-grid').evaluate('(el)=>getComputedStyle(el).gridTemplateColumns.split(" ").length')==1
            initial_hud.get_by_role('button',name='Expand HUD panel',exact=True).click()
            page.wait_for_function("document.querySelector('.fleet-hud-panel').dataset.expanded==='true'")
            assert agent_hud.layout()['agent_panel_expanded'] is True
            page.reload()
            page.wait_for_function("document.querySelector('.fleet-hud-panel')?.dataset.expanded==='true'")
            assert page.title() == 'HARQIS \u2014 Second Brain'
            page.get_by_role('button',name='Animation',exact=True).click()
            animation_menu=page.get_by_role('region',name='Animation modes')
            assert animation_menu.get_by_role('button').count()==4
            animation_menu.get_by_role('button',name='Drift',exact=True).click()
            assert animation_menu.get_by_role('button',name='Drift',exact=True).get_attribute('aria-pressed')=='true'
            assert animation_menu.get_by_role('status').inner_text()=='Paused'
            page.screenshot(path=str(tmp_path/('ecosystem-animation-'+str(width)+'.png')),full_page=True)
            page.keyboard.press('Escape')
            assert page.get_by_role('button',name='Animation',exact=True).evaluate('(el)=>el===document.activeElement')
            page.get_by_role('button',name='Animation',exact=True).click()
            animation_menu.get_by_role('button',name='Off',exact=True).click()
            page.get_by_label('Search agents and outputs').click()
            assert animation_menu.count()==0

            page.get_by_role('button',name='Select Ada · Senior developer',exact=True).click()
            page.get_by_role('button',name='Milo · Test specialist',exact=False).click()
            page.get_by_role('heading',name='Milo · Test specialist',exact=True).wait_for()
            assert page.get_by_text('returns artifact',exact=True).is_visible()
            page.get_by_role('complementary',name='HARQIS Butler HUD feed').wait_for()
            # Clicking the graph background restores the overview and its filters.
            page.locator('.fleet-map canvas').click(position={'x': 5, 'y': 5})
            page.get_by_label('Search agents and outputs').fill('invoices')
            page.wait_for_function("document.querySelectorAll('.fleet-list button').length===2")
            assert page.get_by_role('button',name='Select Atlas · Operations',exact=True).count()==1
            legend_task=page.locator('.fleet-entity-legend').get_by_role('button',name='task',exact=True)
            legend_task.click()
            assert legend_task.get_attribute('aria-pressed')=='false'
            page.wait_for_function("document.querySelectorAll('.fleet-list button').length===0")
            page.get_by_role('button',name='Filters',exact=True).click()
            drawer=page.get_by_role('dialog',name='Filters',exact=True)
            assert not drawer.get_by_label('Task',exact=True).is_checked()
            drawer.get_by_label('Task',exact=True).check()
            page.keyboard.press('Escape')
            assert legend_task.get_attribute('aria-pressed')=='true'
            page.wait_for_function("document.querySelectorAll('.fleet-list button').length===2")

            page.get_by_label('Search agents and outputs').fill('')
            page.get_by_role('button',name='Filters',exact=True).click()
            assert page.get_by_label('Show mock data',exact=True).count()==0
            page.get_by_role('dialog',name='Filters',exact=True).get_by_role('button',name='Close',exact=True).click()
            assert page.get_by_role('button',name='Select Ada · Senior developer',exact=True).count()==1
            page.locator('.fleet-spaces > details > summary').click()
            if width <= 900:
                assert page.locator('.workspace-menu-panel').bounding_box()['y'] >= page.locator('.fleet-spaces > details > summary').bounding_box()['y'] + page.locator('.fleet-spaces > details > summary').bounding_box()['height']
            page.get_by_label('Focus on',exact=True).click()
            page.get_by_label('Work',exact=True).check()
            page.keyboard.press('Escape')
            page.wait_for_function("document.querySelectorAll('.fleet-list button').length===0")
            assert page.locator('.activity-view-modified').inner_text()=='Saved'
            page.get_by_label('Focus on',exact=True).click()
            page.get_by_role('button',name='All activity',exact=True).click()
            page.get_by_role('switch',name='Dynamic mode').check()
            page.wait_for_function("document.querySelector('.activity-dynamic-badge').textContent==='Dynamic ON'")
            page.get_by_role('switch',name='Dynamic mode').uncheck()
            page.wait_for_function("document.querySelector('.activity-dynamic-badge').textContent==='Dynamic OFF'")
            page.keyboard.press('Escape')
            # Escape closes the nested picker first; close its outer Space menu too.
            if page.locator('.fleet-spaces > details').get_attribute('open') is not None:
                page.locator('.fleet-spaces > details > summary').click()
            page.get_by_role('button',name='Select HARQIS Butler',exact=True).click()
            hud=page.get_by_role('complementary',name='HARQIS Butler HUD feed')
            hud.wait_for()
            assert hud.locator('.fleet-hud-card').count()>2
            assert hud.locator('.fleet-hud-grid').evaluate('(el)=>getComputedStyle(el).gridTemplateColumns.split(" ").length')==2
            assert hud.get_by_text('HUD feed',exact=True).count()==0
            card_width=hud.locator('.fleet-hud-card').first.bounding_box()['width']
            grid_width=hud.locator('.fleet-hud-grid').bounding_box()['width']
            assert abs(card_width-grid_width)<2
            if width>900:
                assert abs(hud.evaluate('(el)=>el.clientWidth')-grid_width-20)<2
            assert abs(grid_width-(2*max(154,(width-104)/6)+12))<2
            narrow=hud.locator('[data-id="hud:context"]').bounding_box()
            short=hud.locator('[data-id="hud:monitoring"]').bounding_box()
            assert abs(narrow['width']-(grid_width-12)/2)<2
            assert abs(narrow['y']-short['y'])<2
            assert short['x']>narrow['x']+narrow['width']
            assert narrow['height']>short['height']
            radar=hud.locator('[data-id="hud:hud.hud_radar.show_daily_radar"] .hud-widget-header')
            assert radar.evaluate('(el)=>getComputedStyle(el).borderBottomColor')=='rgb(249, 115, 22)'
            assert hud.locator('.fleet-hud-card').first.evaluate('(el)=>getComputedStyle(el).gridColumnStart')=='span 2'
            before_hud=hud.locator('.fleet-hud-card').evaluate_all('(cards)=>cards.map(card=>card.dataset.id)')
            hud.locator('.fleet-hud-drag').first.focus()
            page.keyboard.press('ArrowRight')
            page.wait_for_function("id=>document.querySelectorAll('.fleet-hud-card')[1]?.dataset.id===id",arg=before_hud[0])
            reordered=hud.locator('.fleet-hud-card').evaluate_all('(cards)=>cards.map(card=>card.dataset.id)')
            if width>900:
                handle=hud.locator('.fleet-hud-drag').first.bounding_box()
                target=hud.locator('.fleet-hud-card').nth(1).bounding_box()
                page.mouse.move(handle['x']+handle['width']/2,handle['y']+handle['height']/2)
                page.mouse.down()
                page.mouse.move(target['x']+target['width']*.75,target['y']+target['height']/2,steps=20)
                page.wait_for_timeout(250)
                page.mouse.up()
                page.wait_for_function("first=>document.querySelector('.fleet-hud-card').dataset.id!==first",arg=reordered[0])
                reordered=hud.locator('.fleet-hud-card').evaluate_all('(cards)=>cards.map(card=>card.dataset.id)')

            radar_card=hud.locator('[data-id="hud:hud.hud_radar.show_daily_radar"]')
            radar_card.locator('.fleet-hud-size-trigger').click()
            size_menu=page.locator('.hud-settings-menu:popover-open')
            size_menu.get_by_role('radio',name='Three column short · 3x1',exact=True).locator('..').click()
            size_menu.get_by_role('radio',name='Typing',exact=True).locator('..').click()
            size_menu.get_by_role('radio',name='Accent #3b82f6',exact=True).locator('..').click()
            size_menu.locator('summary').click()
            size_menu.get_by_role('checkbox',name='HUD Work',exact=True).check()
            size_menu.locator('summary').click()
            page.screenshot(path=str(tmp_path/('ecosystem-hud-menu-'+str(width)+'.png')),full_page=True)
            size_menu.get_by_role('button',name='Save',exact=True).click()
            # A Space-scoped HUD is hidden until that Space is selected.
            radar_card.wait_for(state='detached')
            page.locator('.fleet-spaces > details > summary').click()
            page.get_by_label('Focus on',exact=True).click()
            page.get_by_label('HUD Work',exact=True).check()
            page.keyboard.press('Escape')
            if page.locator('.fleet-spaces > details').get_attribute('open') is not None:
                page.locator('.fleet-spaces > details > summary').click()
            page.wait_for_function("document.querySelector('[data-id=\"hud:hud.hud_radar.show_daily_radar\"]')?.style.getPropertyValue('--cols')==='3'")
            saved_widget=agent_hud.layout()['widgets'][0]
            assert saved_widget['size']=='3x1'
            assert saved_widget['animation']=='typing'
            assert saved_widget['accent']=='#3b82f6'
            assert saved_widget['workspace_ids']==[hud_space['id']]
            shared_widget=shared_hud.layout()['widgets'][0]
            assert shared_widget['size']=='2x2'
            assert shared_widget['accent']=='#f97316'
            assert shared_widget['animation']=='static'
            assert shared_widget['workspace_ids']==[hud_space['id']]
            assert client.get('/second-brain').status_code==200
            assert radar_card.evaluate('(el)=>el.style.getPropertyValue("--cols")')=='3'
            assert hud.evaluate('(el)=>el.scrollWidth>el.clientWidth')
            hud.evaluate('(el)=>{el.scrollLeft=50}')
            assert hud.evaluate('(el)=>el.scrollLeft')>0
            page.screenshot(path=str(tmp_path/('ecosystem-hud-'+str(width)+'.png')),full_page=True)
            page.reload()
            # With no selection the HUD continues to show Butler's available cards.
            hud.wait_for()
            page.wait_for_function("document.querySelector('[data-id=\"hud:hud.hud_radar.show_daily_radar\"]')?.style.getPropertyValue('--cols')==='3'")
            assert hud.locator('.fleet-hud-card').evaluate_all('(cards)=>cards.map(card=>card.dataset.id)')==reordered
            assert hud.locator('[data-id="hud:hud.hud_radar.show_daily_radar"]').evaluate('(el)=>el.style.getPropertyValue("--cols")')=='3'
            radar_card.locator('.fleet-hud-size-trigger').click()
            external=agent_hud.layout()
            external['widgets'][0]['accent']='#14b8a6'
            assert client.put('/agents/hud/layout',json=external,headers=hud_headers).status_code==200
            size_menu.get_by_role('button',name='Save',exact=True).click()
            size_menu.get_by_role('alert').filter(has_text='changed in another view').wait_for()
            assert agent_hud.layout()['widgets'][0]['accent']=='#14b8a6'
            assert shared_hud.layout()['widgets'][0]['accent']=='#f97316'
            page.keyboard.press('Escape')
            for operation,action in [('monitoring','Hide'),('context','Remove')]:
                target_card=hud.locator('[data-id="hud:'+operation+'"]')
                target_card.locator('.fleet-hud-size-trigger').click()
                settings=page.locator('.hud-settings-menu:popover-open')
                if operation=='monitoring':
                    assert settings.get_by_label('Kibana dashboard share URL').is_visible()
                settings.get_by_role('button',name=action,exact=True).click()
                target_card.wait_for(state='detached')
            shared=agent_hud.layout()['widgets']
            assert next(w for w in shared if w['operation']=='monitoring')['hidden']
            assert not any(w['operation']=='context' for w in shared)
            assert not next(w for w in shared_hud.layout()['widgets'] if w['operation']=='monitoring')['hidden']
            assert any(w['operation']=='context' for w in shared_hud.layout()['widgets'])

            # Restore all agents before testing graph dragging and fullscreen.
            page.locator('.fleet-spaces > details > summary').click()
            page.get_by_label('Focus on',exact=True).click()
            page.get_by_role('button',name='All activity',exact=True).click()
            page.keyboard.press('Escape')
            if page.locator('.fleet-spaces > details').get_attribute('open') is not None:
                page.locator('.fleet-spaces > details > summary').click()
            page.get_by_role('button',name='Select HARQIS Butler',exact=True).click()
            page.evaluate('window.scrollTo(0,0)')
            page.wait_for_timeout(1800)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert page.locator('.fleet-workspace').bounding_box()['y'] + page.locator('.fleet-workspace').bounding_box()['height'] <= height
            if width >= 1400:
                assert page.locator('.fleet-toolbar').bounding_box()['height'] < 50
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
            # The selected agent inspector replaces the overview list.
            assert page.locator('.fleet-list button').count()==0
            assert page.locator('.fleet-inspector').get_by_role('heading',name='HARQIS Butler',exact=True).is_visible()
            page.get_by_role('button',name='Zoom in',exact=True).click()
            page.get_by_role('button',name='Zoom out',exact=True).click()
            page.get_by_role('button',name='Fit view',exact=True).click()
            page.get_by_role('button',name='Fullscreen',exact=True).click()
            page.wait_for_function("document.getElementById('agent-fleet').classList.contains('fleet-fullscreen')")
            assert page.locator('.fleet-workspace').bounding_box()['y']==0
            assert page.get_by_role('button',name='Exit fullscreen',exact=True).evaluate('(el)=>el===document.activeElement')
            assert page.locator('.fleet-inspector').is_visible()
            page.locator('.fleet-map canvas').click(position={'x':15,'y':15})
            page.locator('.fleet-inspector').wait_for(state='hidden')
            page.get_by_role('complementary',name='HARQIS Butler HUD feed').wait_for()
            if width>900:
                page.wait_for_function("Math.abs(document.querySelector('.fleet-map').getBoundingClientRect().right-innerWidth)<5")
            else:
                page.wait_for_function("document.querySelector('.fleet-map').getBoundingClientRect().width > innerWidth-5")

            assert page.locator('.fleet-toolbar').is_hidden()
            page.screenshot(path=str(tmp_path/('ecosystem-fullscreen-'+str(width)+'.png')),full_page=True)
            page.keyboard.press('Escape')
            assert page.get_by_role('button',name='Fullscreen',exact=True).evaluate('(el)=>el===document.activeElement')
            assert page.locator('.fleet-toolbar').is_visible()
            assert page.get_by_role('complementary',name='HARQIS Butler HUD feed').is_visible()
            # Persist the complete filter selection and hidden-node positions across reload.
            page.get_by_role('button',name='Filters',exact=True).click()
            drawer=page.get_by_role('dialog',name='Filters',exact=True)
            drawer.get_by_label('Show deactivated',exact=True).check()
            drawer.get_by_label('Service',exact=True).select_option('hermes')
            drawer.get_by_label('From date',exact=True).fill('2026-01-01')
            drawer.get_by_label('Through date',exact=True).fill('2026-12-31')
            drawer.get_by_label('Task',exact=True).uncheck()
            page.keyboard.press('Escape')
            page.get_by_label('Search agents and outputs').fill('Butler')
            page.get_by_role('button',name='Animation',exact=True).click()
            page.get_by_role('region',name='Animation modes').get_by_role('button',name='Off',exact=True).click()
            page.keyboard.press('Escape')
            saved_positions=page.evaluate("JSON.parse(localStorage.getItem('harqis:fleet:graph:v2:frontend-test-user')).positions")
            assert any('demo-' in identity for identity in saved_positions)
            page.reload()
            page.get_by_role('button',name='Filters',exact=True).click()
            drawer=page.get_by_role('dialog',name='Filters',exact=True)
            assert drawer.get_by_label('Show deactivated',exact=True).is_checked()
            assert drawer.get_by_label('Show mock data',exact=True).count()==0
            assert drawer.get_by_label('Service',exact=True).input_value()=='hermes'
            assert drawer.get_by_label('From date',exact=True).input_value()=='2026-01-01'
            assert drawer.get_by_label('Through date',exact=True).input_value()=='2026-12-31'
            assert not drawer.get_by_label('Task',exact=True).is_checked()
            assert page.get_by_label('Search agents and outputs').input_value()=='Butler'
            restored=page.evaluate("JSON.parse(localStorage.getItem('harqis:fleet:graph:v2:frontend-test-user')).positions")
            for identity,position in saved_positions.items():
                if 'demo-' in identity:
                    assert restored[identity]==position
            page.keyboard.press('Escape')
            page.screenshot(path=str(tmp_path/('ecosystem-'+str(width)+'.png')),full_page=True)
            assert not errors,errors
        finally:
            if 'page' in locals():
                page.screenshot(path=str(tmp_path/('ecosystem-final-'+str(width)+'.png')),full_page=True)
            browser.close()
