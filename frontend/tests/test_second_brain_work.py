"""Work navigation, contextual handoff and recorded agent updates."""
from urllib.parse import urlparse
import pytest
from test_agent_fleet import fleet  # noqa: F401
from test_hfl_agent_bridge import bridge  # noqa: F401


def test_context_resolves_agent_and_spaces_without_trusting_browser_text(fleet, monkeypatch):
    from modules.agents import assistant, ecosystem
    fleet.initialize()
    monkeypatch.setattr(ecosystem, 'graph', lambda user: {
        'agents': [{'id':'butler','name':'HARQIS Butler'}],
        'nodes': [{'id':'a','kind':'action','label':'Work A','agent_ids':['butler'], 'workspace_ids':['work']},
                  {'id':'b','kind':'action','label':'Personal','agent_ids':['butler'], 'workspace_ids':['home']}],
        'warnings': []})
    result = assistant.page_context({'version':1,'path':'/agents','agent_id':'butler','workspace_ids':['work']}, 'owner')
    assert [r['label'] for r in result['agent_activity']] == ['Work A']
    assert result['agent_activity'][0]['agents'] == ['HARQIS Butler']
    with pytest.raises(ValueError):
        assistant.page_context({'version':1,'path':'/agents','workspace_ids':'work'}, 'owner')
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        assistant.page_context({'version':1,'path':'/agents','agent_id':'missing'}, 'owner')


def test_agent_update_deduplicates_attempts_and_excludes_scheduled_answers(fleet, bridge, monkeypatch):
    from modules.agents import briefings
    from modules.hfl_corpus import action_agents
    fleet.initialize()
    def run(identity, source, state):
        return {'id':identity,'source_key':'actionable:'+source,'state':state,'updated_at':'2026-11-15T10:00:00Z',
                'snapshot':{'execution_settings':{'fleet_agent':{'id':'butler'}},'source':{'title':source,'workspace_ids':['work']}},
                'result':{'summary':'Recorded result'}}
    class Store:
        def list(self, **kwargs):
            return [run('new','task','review'),run('old','task','failed'),run('scheduled','briefing','succeeded')]
    monkeypatch.setattr(action_agents, 'store', lambda: Store())
    with fleet.store().connect() as db:
        db.execute('INSERT INTO fleet_chat(user,request_id,message,created,run_id) VALUES (?,?,?,?,?)',
                   ('owner','key','Scheduled briefing','2026-11-15','scheduled'))
    updates=briefings.agent_updates('owner')
    assert len(updates)==1
    assert updates[0]['id']=='agent-update:new'
    assert updates[0]['agent_name']=='HARQIS Butler'
    assert updates[0]['workspace_ids']==['work']


@pytest.mark.parametrize('width,height',[(1440,1000),(390,844)])
def test_work_drawer_and_butler_handoff_browser(fleet, bridge, authenticated_client, tmp_path, width, height):
    from modules.agents import ecosystem
    fleet.initialize()
    snapshot=ecosystem.graph('frontend-test-user')
    identity='action:item-'+'a'*32
    snapshot['nodes'].append({'id':identity,'kind':'action','label':'Review delivery result','agent_ids':['butler'],
        'workspace_ids':[],'state':'in_progress','record':{'status':'in_progress'},'created':'2026-11-15T10:00:00Z','color':'#facc15',
        'execution':{'id':'run-1','agent_id':'butler','state':'failed','updated_at':'2026-11-15T10:00:00Z','url':'/hfl-corpus/actions?integration_agent=item-'+'a'*32}})
    snapshot['edges'].append({'source':'agent:butler','target':identity,'relation':'assigned to'})
    pw=pytest.importorskip('playwright.sync_api')
    with pw.sync_playwright() as engine:
        browser=engine.chromium.launch(channel='chrome',headless=True)
        try:
            page=browser.new_page(viewport={'width':width,'height':height})
            errors=[];writes=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            def route(r):
                u=urlparse(r.request.url)
                if r.request.method=='POST': writes.append(u.path)
                if u.path=='/agents/api/graph':r.fulfill(json=snapshot);return
                if u.path=='/agents/api/assistant':r.fulfill(json={'active':True,'connected':False,'agent_id':'butler','host':''});return
                response=authenticated_client.request(r.request.method,u.path+('?' + u.query if u.query else ''),
                    content=r.request.post_data_buffer,headers={k:v for k,v in r.request.headers.items() if k in {'content-type','x-csrf-token'}})
                r.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get('content-type','text/html'))
            page.route('https://work.test/**',route)
            page.goto('https://work.test/agents')
            panel=page.get_by_role('complementary',name='Agent work')
            pw.expect(panel).to_be_visible()
            pw.expect(panel.get_by_role('region',name='Needs attention')).to_be_visible()
            pw.expect(panel.get_by_text('Execution: failed',exact=True)).to_be_visible()
            pw.expect(panel.get_by_text('Action: in progress',exact=True)).to_be_visible()
            assert page.locator('.fleet-hud-panel').count()==0
            nav=page.get_by_role('navigation',name='Second Brain views')
            assert nav.get_by_role('link',name='Kanban').get_attribute('href')=='/hfl-corpus/actions'
            assert page.locator('nav[aria-label="Express tools"] a[href="/hfl-corpus/actions"]').count()==2
            assert page.locator('nav[aria-label="Distill views"] a[href="/agents"]').count()==0
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(tmp_path / f'agent-work-{width}.png'))
            panel.get_by_role('button',name='Ask Butler',exact=True).click()
            pw.expect(page.locator('#butler-panel')).to_be_visible()
            pw.expect(page.locator('#butler-context')).to_contain_text('Attached context: Agent work')
            pw.expect(page.locator('#butler-message')).to_have_value('What needs my attention in the current agent work?')
            assert not writes
            page.screenshot(path=str(tmp_path / f'butler-context-{width}.png'))
            assert not errors,errors
        finally:
            browser.close()
