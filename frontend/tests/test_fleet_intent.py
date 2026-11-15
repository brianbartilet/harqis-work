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
    assert nodes['action:a']['color'] == '#facc15'
    assert nodes['action:a']['status_color'] == '#4ade80'
    assert nodes['action:orphan']['agent_ids'] == []
    assert nodes['idea:i']['agent_ids'] == ['butler']
    assert nodes['idea:m']['agent_ids'] == [] and nodes['idea:m']['status_color'] == '#94a3b8'
    assert nodes['entry:e']['agent_ids'] == ['ada']
    assert nodes['entry:s']['agent_ids'] == ['sharing']
    assert nodes['entry:unattributed']['agent_ids'] == []
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


def test_fleet_inline_intent_browser(fleet, bridge, authenticated_client, tmp_path):
    import pytest
    from urllib.parse import urlparse
    from uuid import uuid4
    pw=pytest.importorskip('playwright.sync_api')
    from modules.hfl_corpus.action_agents import store
    from modules.agents import briefings
    item=bridge[2].create({'request_id':str(uuid4()),'title':'Review fleet integration','expected_outcome':'## Inventory management\n\n- Review current stock\n- Confirm pending orders'},actor='owner')[0]
    store().configure('card:'+item['id'],{'agent_id':'butler'})
    idea_response=authenticated_client.post('/hfl-corpus/timeline/ideas/objects',json={'request_id':str(uuid4()),'title':'Review fleet idea','description':'## Plan\n\n- Read the matched entries\n- Curate the next step'})
    assert idea_response.status_code==200,idea_response.text
    idea=idea_response.json()['item']
    store().configure('idea:'+idea['id'],{'agent_id':'butler'})
    fleet.initialize()
    briefings.seed_demo('frontend-test-user')
    errors=[]
    with pw.sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror',lambda error:errors.append(str(error)))
        workspace={'views':[{'id':'work','name':'Work','color':'#67e8f9','schedule':[{'days':[0,1,2,3,4,5,6],'start':'00:00','end':'23:59'}]}], 'preferences':{'dynamic':False,'manual':[],'revision':0},'active':[]}
        def route(r):
            u=urlparse(r.request.url)
            if u.path=='/hfl-corpus/workspace-views':
                r.fulfill(json=workspace);return
            if u.path=='/hfl-corpus/view-preferences':
                import json
                requested=json.loads(r.request.post_data)
                if requested.get('revision') != workspace['preferences']['revision']:
                    r.fulfill(status=409,json={'detail':'View settings changed in another tab. Reload and retry.'});return
                workspace['preferences'].update(requested)
                workspace['preferences']['revision']+=1
                workspace['active']=['work'] if workspace['preferences']['dynamic'] else workspace['preferences']['manual']
                r.fulfill(json=workspace);return
            response=authenticated_client.request(r.request.method,u.path+('?' + u.query if u.query else ''),content=r.request.post_data_buffer,
                headers={k:v for k,v in r.request.headers.items() if k in {'content-type','x-csrf-token'}})
            r.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','text/html'))
        page.route('https://fleet.test/**',route)
        try:
            page.goto('https://fleet.test/agents?agent=butler')
            page.locator('.fleet-layout-loading').wait_for(state='hidden')
            position_script="JSON.parse(localStorage.getItem('harqis:fleet:graph:v2:frontend-test-user')).positions"
            before=page.evaluate(position_script)
            assert 'action:'+item['id'] in before
            page.reload()
            page.locator('.fleet-layout-loading').wait_for(state='hidden')
            assert page.evaluate(position_script)==before
            search=page.get_by_label('Search agents and outputs')
            search.fill('no-matching-entity')
            page.wait_for_timeout(200)
            search.fill('')
            page.wait_for_timeout(1600)
            page.evaluate("window.dispatchEvent(new Event('pagehide'))")
            assert page.evaluate(position_script)==before
            # Exercise real keyboard events and the nested Space picker.
            page.locator('.fleet-hotkeys').click()
            pw.expect(page.locator('#activity-hotkey-help')).to_be_visible()
            page.keyboard.press('k')
            pw.expect(page.locator('#activity-hotkey-help')).not_to_be_visible()
            page.keyboard.press('f')
            pw.expect(page.locator('#fleet-filter-drawer')).to_be_visible()
            page.keyboard.press('Escape')
            page.get_by_role('button',name='Fullscreen',exact=True).click()
            page.locator('.fleet-spaces > details > summary').click()
            page.get_by_label('Focus on',exact=True).click()
            page.locator('.fleet-spaces .workspace-view-options input[value="work"]').check()
            workspace['preferences']['revision']+=1
            page.locator('.fleet-spaces > details > summary').click()
            page.wait_for_function("document.querySelector('.activity-view-name').textContent==='Work'")
            page.locator('.fleet-hotkeys').focus()
            page.keyboard.press('Alt+Backquote')
            page.wait_for_function("document.querySelector('.activity-view-name').textContent==='All activity'")
            page.keyboard.press('Alt+1')
            page.wait_for_function("document.querySelector('.activity-view-name').textContent==='Work'")
            page.keyboard.press('Alt+Backquote')
            page.wait_for_function("document.querySelector('.activity-view-name').textContent==='All activity'")
            page.keyboard.press('n')
            page.wait_for_function("document.querySelector('.activity-dynamic-badge').textContent==='Dynamic ON'")
            pw.expect(page.locator('.fleet-spaces [role=switch]')).to_be_enabled()
            page.keyboard.press('n')
            page.wait_for_function("document.querySelector('.activity-dynamic-badge').textContent==='Dynamic OFF'")
            page.screenshot(path=str(tmp_path/'fleet-fullscreen-controls.png'))
            page.set_viewport_size({'width':390,'height':844})
            pw.expect(page.locator('.fleet-spaces > details > summary')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(tmp_path/'fleet-fullscreen-mobile.png'))
            page.set_viewport_size({'width':1440,'height':1000})
            page.get_by_role('button',name='Exit fullscreen',exact=True).click()
            # Both manual and scheduled Space transitions preserve hidden children.
            page.evaluate("document.dispatchEvent(new CustomEvent('fleet-space-key',{detail:1}))")
            page.wait_for_function("document.querySelector('.activity-view-name').textContent==='Work'")
            page.evaluate("document.dispatchEvent(new CustomEvent('fleet-space-key',{detail:0}))")
            page.wait_for_function("document.querySelector('.activity-view-name').textContent==='All activity'")
            page.locator('.fleet-spaces > details > summary').click()
            page.get_by_role('switch',name='Dynamic mode').check()
            page.get_by_role('switch',name='Dynamic mode').focus()
            page.keyboard.press('k')
            pw.expect(page.locator('#activity-hotkey-help')).to_be_visible()
            page.keyboard.press('k')
            page.wait_for_function("document.querySelector('.activity-dynamic-badge').textContent==='Dynamic ON'")
            page.get_by_role('switch',name='Dynamic mode').uncheck()
            page.wait_for_function("document.querySelector('.activity-dynamic-badge').textContent==='Dynamic OFF'")
            page.keyboard.press('Escape')
            page.wait_for_timeout(1600)
            page.evaluate("window.dispatchEvent(new Event('pagehide'))")
            assert page.evaluate(position_script)==before
            if page.locator('.fleet-spaces > details').get_attribute('open') is not None:
                page.locator('.fleet-spaces > details > summary').click()
            # Fleet filters are independent of manual and scheduled Space changes.
            search.fill('Review')
            page.locator('.fleet-filter-trigger').click()
            page.get_by_label('Service',exact=True).select_option('hermes')
            page.get_by_label('From date',exact=True).fill('2026-01-01')
            page.get_by_label('Through date',exact=True).fill('2026-12-31')
            page.get_by_role('switch',name='Show done and dismissed items').check()
            page.keyboard.press('Escape')
            filters_script="""() => {const v=JSON.parse(localStorage.getItem('harqis:fleet:graph:v2:frontend-test-user'));return Object.fromEntries(['query','range','since','until','runtime','types','inactive','dismissed','includeOwnerActivity'].map(k=>[k,v[k]]));}"""
            saved_filters=page.evaluate(filters_script)
            page.locator('.fleet-hotkeys').focus()
            page.keyboard.press('Alt+1')
            page.wait_for_function("document.querySelector('.activity-view-name').textContent==='Work'")
            assert page.evaluate(filters_script)==saved_filters
            # A scheduled transition arrives through the periodic snapshot loader.
            workspace['preferences']['dynamic']=True
            workspace['active']=[]
            page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            page.wait_for_function("document.querySelector('.activity-view-name').textContent==='All activity'")
            assert page.evaluate(filters_script)==saved_filters
            assert page.locator('.fleet-spaces .activity-view-modified').count()==0
            page.locator('.fleet-filter-trigger').click()
            page.get_by_role('button',name='Reset filters',exact=True).click()
            page.keyboard.press('Escape')
            search.fill(item['title'])
            page.locator('.fleet-owner .fleet-relationship-card').click()
            pw.expect(page.locator('.fleet-relationships .fleet-relationship-card')).to_have_count(1)
            assert page.locator('.fleet-relationships .fleet-relationship-type').inner_text()=='action'
            assert page.get_by_role('button',name='Show more',exact=False).count()==0
            search.fill('')
            page.locator('.fleet-map canvas').click(position={'x':5,'y':5})
            page.get_by_role('button',name='Select HARQIS Butler',exact=True).click()
            page.locator('.fleet-output-list button').filter(has_text=idea['title']).click()
            idea_controls=page.locator('.fleet-intent-controls')
            assert idea_controls.get_by_role('button',name='Restore',exact=True).count()==0
            assert page.locator('.fleet-idea-assignment').count()==0
            assert idea_controls.evaluate('(el)=>getComputedStyle(el).gridTemplateColumns.split(" ").length')==1
            page.locator('.fleet-description-details').get_by_text('Description',exact=True).click()
            page.screenshot(path=str(tmp_path/'fleet-idea-desktop.png'))
            idea_controls.get_by_role('button',name='Dismiss',exact=True).click()
            pw.expect(page.locator('.fleet-agent-overview')).to_be_visible()
            assert authenticated_client.get('/hfl-corpus/timeline/ideas/objects/'+idea['id']).json()['item']['status']=='dismissed'
            page.get_by_role('button',name='Select HARQIS Butler',exact=True).click()

            page.locator('.fleet-output-list button').filter(has_text=item['title']).click()
            controls=page.locator('.fleet-intent-controls')
            description=page.locator('.fleet-description-details')
            assert description.get_attribute('open') is None
            description.get_by_text('Description',exact=True).click()
            assert description.get_attribute('open') is not None
            assert page.locator('.fleet-idea-assignment').count()==0
            assert page.locator('.fleet-relationship-type').count()>0
            assert controls.evaluate('(el)=>getComputedStyle(el).gridTemplateColumns.split(" ").length')==1
            page.screenshot(path=str(tmp_path/'fleet-inspector-desktop.png'))
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(tmp_path/'fleet-inspector-mobile.png'))
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.set_viewport_size({'width':1440,'height':1000})

            page.get_by_role('button',name='Fullscreen',exact=True).click()
            controls.get_by_role('button',name='Edit',exact=True).click()
            pw.expect(page.locator('#followup-editor')).to_be_visible()
            assert not page.locator('#followup-editor').evaluate('el=>el.inert')
            assert '/agents' in page.url
            page.keyboard.press('Escape')
            page.get_by_role('button',name='Exit fullscreen',exact=True).click()
            controls.get_by_role('button',name='Done',exact=True).click()
            pw.expect(page.locator('.fleet-agent-overview')).to_be_visible()
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


def test_owner_links_history_without_inventing_authorship(fleet, monkeypatch):
    from types import SimpleNamespace
    from modules.agents.corpus_projection import extend, add_owner, description_html
    from modules.profile import store as profiles
    monkeypatch.setattr(profiles, 'get_profile_store', lambda: SimpleNamespace(get=lambda: SimpleNamespace(display_name='Corpus Owner',bio='My corpus',avatar_data_uri='')))
    nodes, edges = {}, {}
    extend(nodes, edges, [{'id':'butler'}], {}, {'actions':[{'id':'a','title':'Manual action','status':'open'}]},
           [{'id':'old','source':'manual-entry','text':'Source: manual-entry\nWhat happened: A historical note\nNext line','path':'history.md','date':'2020-01-01'}])
    add_owner(nodes, edges)
    assert nodes['owner:corpus']['label'] == 'Corpus Owner'
    assert nodes['entry:old']['agent_ids'] == []
    assert ('entry:old','owner:corpus','belongs to corpus') in edges
    assert ('action:a','owner:corpus','belongs to corpus') in edges
    html = description_html('What happened: Example\n\n<script>alert(1)</script>\n\n## Heading')
    assert '<strong>What happened</strong>' in html and '<h2>Heading</h2>' in html
    assert '<script' not in html


def test_idea_assignment_validates_and_preserves_other_relationships(fleet, authenticated_client, monkeypatch):
    from modules.hfl_corpus import ideas_api
    from modules.hfl_corpus.action_agents import store
    from modules.agents.corpus_projection import extend
    fleet.initialize()
    idea={'id':'i','title':'Generated idea','status':'suggested'}
    monkeypatch.setattr(ideas_api,'canonical_snapshot',lambda **kw:{'ideas':[idea]})
    client=authenticated_client
    assert post(client,'/ideas/missing/assignment',{'agent_id':'butler'}).status_code == 404
    assert post(client,'/ideas/i/assignment',{'agent_id':'missing'}).status_code == 422
    assert post(client,'/ideas/i/assignment',{'agent_id':'butler'}).status_code == 200
    assert post(client,'/ideas/i/assignment',{'agent_id':'','previous_agent_id':''}).status_code == 409
    nodes,edges={},{}
    extend(nodes,edges,[{'id':'butler'}],store().configs(),{'ideas':[idea]},[])
    assert ('agent:butler','idea:i','assigned to') in edges
    assert ('agent:butler','idea:i','monitors generated idea') in edges
    assert post(client,'/ideas/i/assignment',{'agent_id':'','previous_agent_id':'butler'}).status_code == 200
    extend(nodes,edges,[{'id':'butler'}],store().configs(),{'ideas':[idea]},[])
    assert ('agent:butler','idea:i','assigned to') not in edges
    assert ('agent:butler','idea:i','monitors generated idea') in edges


def test_entry_description_only_reads_permitted_entries(fleet, authenticated_client, monkeypatch):
    from modules.hfl_corpus import fleet_entry_cache
    monkeypatch.setattr(fleet_entry_cache,'current_entries',lambda:[{'id':'allowed','text':'What happened: Note\nTags: #sharing #audit\n\n<script>bad()</script>'}])
    response=authenticated_client.get('/agents/api/entries/allowed/description')
    assert response.status_code == 200
    html=response.json()['html']
    assert '<strong>What happened</strong>' in html
    assert '#sharing #audit' in html and '<h1>' not in html and '<script' not in html
    assert authenticated_client.get('/agents/api/entries/protected/description').status_code == 404
