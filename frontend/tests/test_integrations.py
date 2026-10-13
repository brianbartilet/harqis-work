"""Connector security boundaries and full provider flows with deterministic API doubles."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from fastapi import HTTPException
from modules.integrations import store, service, providers
from modules.hfl_shares.security import make_csrf_token

BASE = '/integrations/api'
USER = 'frontend-test-user'


@pytest.fixture
def connectors(monkeypatch, tmp_path):
    monkeypatch.setenv('HARQIS_CONNECTORS_DB', str(tmp_path/'connectors.sqlite3'))
    monkeypatch.setenv('HFL_TIMELINE_LOCAL_PREVIEW', '1')
    monkeypatch.setenv('HFL_AGENT_BRIDGE_STORE_PATH', str(tmp_path/'agents.sqlite3'))
    state = {'branches':{'main':'abc'}, 'pulls':[], 'status':'1', 'calls':[], 'fail':False}
    def issue():
        status = {'1':('To Do','new'), '2':('In Progress','indeterminate'), '3':('Done','done')}[state['status']]
        return {'id':'100', 'key':'TEST-1', 'fields':{'summary':'Ship connected work', 'status':{'id':state['status'],'name':status[0],'statusCategory':{'key':status[1]}}, 'assignee':{'accountId':'jira-user'}, 'project':{'key':'TEST'}}}
    def request(self, method, path, *, params=None, json=None, missing=False):
        state['calls'].append((self.provider,method,path,json))
        if state['fail']:
            raise HTTPException(401, 'Token expired, revoked, or invalid. Reconnect.')
        if path == '/user': return {'login':'alice','id':1}
        if path == '/rest/api/3/myself': return {'displayName':'Alice','accountId':'jira-user'}
        if path == '/user/repos': return [{'full_name':'alice/demo','default_branch':'main','permissions':{'push':True}}]
        if path == '/repos/alice/demo': return {'full_name':'alice/demo'}
        if path == '/repos/alice/demo/branches': return [{'name':b} for b in state['branches']]
        if '/git/ref/heads/' in path:
            from urllib.parse import unquote
            b=unquote(path.split('/heads/')[1])
            if b not in state['branches']:
                if missing:return None
                raise HTTPException(404,'Not found')
            return {'object':{'sha':state['branches'][b]}}
        if path.endswith('/git/refs'):
            b=json['ref'].removeprefix('refs/heads/')
            state['branches'][b]=json['sha'];return {'object':{'sha':json['sha']}}
        if path == '/repos/alice/demo/pulls':
            if method=='GET':return state['pulls']
            result={'number':1,'title':json['title'],'head':{'ref':json['head'],'repo':{'full_name':'alice/demo'}},'state':'open','draft':True}
            state['pulls'].append(result);return result
        if path == '/repos/alice/demo/pulls/1':return state['pulls'][0]
        if path == '/rest/api/3/project/search':return {'values':[{'key':'TEST','name':'Test project'}],'isLast':True}
        if path == '/rest/api/3/search/jql':return {'issues':[issue()]}
        if path == '/rest/api/3/issue/TEST-1':return issue()
        if path == '/rest/api/3/issue/TEST-1/transitions':
            if method=='POST':state['status']=json['transition']['id'];return {}
            return {'transitions':[{'id':'2','name':'Start progress','to':{'name':'In Progress'},'fields':{}},{'id':'3','name':'Complete','to':{'name':'Done'},'fields':{}}]}
        raise AssertionError((method,path))
    monkeypatch.setattr(providers.Provider,'request',request)
    return state


def post(client,path,raw=None,user=USER):
    return client.post(BASE+path,json=raw or {},headers={'X-CSRF-Token':make_csrf_token(user)})


def connect(client,provider):
    raw={'token':'private-test-token','site':'https://example.atlassian.net','email':'alice@example.com'}
    response=post(client,'/connectors/'+provider+'/connect',raw)
    assert response.status_code==200,response.text
    assert not response.json()['enabled']
    assert post(client,'/connectors/'+provider+'/toggle',{'enabled':True}).status_code==200


def card(client):
    return client.post('/hfl-corpus/timeline/items',json={'request_id':str(uuid4()),'title':'Ship integration','agent_enabled':False}).json()['item']


def test_connection_encryption_isolation_disable_and_disconnect(connectors,authenticated_client):
    client=authenticated_client
    assert client.post(BASE+'/connectors/github/connect',json={'token':'secret'}).status_code==403
    connect(client,'github')
    assert 'private-test-token' not in client.get(BASE+'/connectors').text
    with store.connection() as db:
        assert 'private-test-token' not in db.execute('SELECT credentials FROM connectors').fetchone()[0]
    assert store.get('other-user','github')['status']=='Not connected'
    from auth import create_session_token
    client.cookies.set('session',create_session_token('other-user'))
    assert client.get(BASE+'/github/repositories').status_code==409
    client.cookies.set('session',create_session_token(USER))
    post(client,'/connectors/github/toggle',{'enabled':False})
    assert client.get(BASE+'/github/repositories').status_code==409
    assert store.get(USER,'github',private=True)['credentials']['token']=='private-test-token'
    post(client,'/connectors/github/disconnect')
    assert store.get(USER,'github',private=True)['credentials']=={}


def test_failed_connection_cannot_be_enabled(connectors,authenticated_client):
    connectors['fail']=True
    assert post(authenticated_client,'/connectors/github/connect',{'token':'test'}).status_code==401
    assert store.get(USER,'github')['status']=='Not connected'
    assert post(authenticated_client,'/connectors/github/toggle',{'enabled':True}).status_code==409


def test_github_branch_pr_reconciliation_and_user_links(connectors,authenticated_client):
    c=authenticated_client;connect(c,'github');item=card(c);root='/actions/'+item['id']+'/github'
    data={'repository':'alice/demo','branch':'feature/test','base':'main','operation':'create-branch'}
    for _ in range(2):assert post(c,root+'/branch',data).status_code==200
    assert len([call for call in connectors['calls'] if call[2].endswith('/git/refs')])==1
    linked=c.get(BASE+'/actions/'+item['id']).json()['github'][0]
    for _ in range(2):
        result=post(c,root+'/pr',{'resource':linked['resource']})
        assert result.status_code==200,result.text
    assert len(connectors['pulls'])==1
    assert connectors['pulls'][0]['draft']
    connectors['pulls'][0].update(state='closed',merged=True)
    assert c.get(BASE+root).json()['items'][0]['pr_state']=='merged'
    from auth import create_session_token
    c.cookies.set('session',create_session_token('other'))
    assert c.get(BASE+'/actions/'+item['id']).json()=={}


def test_jira_import_transition_and_generic_status_guard(connectors,authenticated_client):
    c=authenticated_client;connect(c,'jira')
    first=post(c,'/jira/import',{'project':'TEST'}).json()['items'][0]
    second=post(c,'/jira/import',{'project':'TEST'}).json()['items'][0]
    assert first['id']==second['id'] and second['status']=='active'
    generic=c.patch('/hfl-corpus/timeline/items/'+first['id'],json={'version':second['version'],'status':'done'})
    assert generic.status_code==409
    root='/actions/'+first['id']+'/jira'
    state=c.get(BASE+root).json()
    payload={'version':state['item']['version'],'expected_status':'1','transition':'2'}
    result=post(c,root+'/transition',payload)
    assert result.status_code==200,result.text
    assert result.json()['item']['status']=='in_progress'
    assert post(c,root+'/transition',payload).status_code==409
    connectors['fail']=True
    assert post(c,root+'/transition',{'version':result.json()['item']['version'],'expected_status':'2','transition':'3'}).status_code==401
    assert service.action(first['id'])['status']=='in_progress'


@pytest.mark.parametrize('site',['http://example.atlassian.net','https://localhost','https://example.atlassian.net.evil.test','https://example.atlassian.net@evil.test','https://example.atlassian.net/path'])
def test_jira_rejects_credential_exfiltration_targets(connectors,authenticated_client,site):
    assert post(authenticated_client,'/connectors/jira/connect',{'token':'test','email':'a@b.com','site':site}).status_code==422
    assert connectors['calls']==[]


def test_agent_preparation_is_durable_and_does_not_execute(connectors,authenticated_client):
    c=authenticated_client
    raw={'name':'example_new_app','description':'Read useful data','create':True,'agent':'hermes'}
    a=post(c,'/agents/prepare',raw);assert a.status_code==200,a.text
    b=post(c,'/agents/prepare',raw)
    assert a.json()['item']['id']==b.json()['item']['id']
    item=a.json()['item'];assert item['agent_enabled'] is False
    assert '$create-new-service-app' in item['prompt']
    assert not Path('apps/example_new_app').exists()
    from modules.hfl_corpus.action_agents import store as terminals
    assert terminals().sessions()==[]
    assert post(c,'/agents/prepare',{**raw,'agent':'codex'}).status_code==422
    assert post(c,'/agents/prepare',{**raw,'name':'../escape'}).status_code==422


@pytest.mark.parametrize('width',[390,1200])
def test_connector_setup_and_github_flow_in_browser(connectors,authenticated_client,monkeypatch,tmp_path,width):
    from modules.hfl_corpus import router
    monkeypatch.setattr(router.corpus_index,'documents',lambda **kwargs:())
    playwright=pytest.importorskip('playwright.sync_api')
    item=card(authenticated_client)
    with playwright.sync_playwright() as engine:
        options={'headless':True}
        if not Path(engine.chromium.executable_path).exists():options['channel']='msedge'
        browser=engine.chromium.launch(**options)
        page=browser.new_page(viewport={'width':width,'height':900});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        def route(intercept):
            req=intercept.request;url=urlsplit(req.url)
            if url.hostname!='integrations.test':intercept.abort();return
            response=authenticated_client.request(req.method,url.path+('?' + url.query if url.query else ''),content=req.post_data,
                headers={k:v for k,v in req.headers.items() if k.lower() in {'content-type','x-csrf-token'}})
            intercept.fulfill(status=response.status_code,body=response.content,headers={'content-type':response.headers.get('content-type','text/html')})
        page.route('**/*',route)
        try:
            page.goto('https://integrations.test/applications')
            connector_tab=page.get_by_role('tab',name='Connectors')
            workflow_tab=page.get_by_role('tab',name='Workflows')
            playwright.expect(connector_tab).to_have_attribute('aria-selected','true')
            playwright.expect(page.locator('#workflow-integrations')).to_be_hidden()
            github=page.locator('.connector-card').filter(has=page.get_by_role('heading',name='GitHub',exact=True))
            github.get_by_role('button',name='Connect',exact=True).click()
            setup=page.locator('.integration-dialog[open]');setup.get_by_label('API token',exact=True).fill('test-token')
            playwright.expect(setup.get_by_role('button',name='Save',exact=True)).to_be_disabled()
            setup.get_by_role('button',name='Test',exact=True).click()
            playwright.expect(setup.get_by_role('status')).to_have_text('Test passed · Not saved')
            assert store.get(USER,'github')['status']=='Not connected'
            setup.get_by_label('API token',exact=True).fill('changed-token')
            playwright.expect(setup.get_by_role('button',name='Save',exact=True)).to_be_disabled()
            setup.get_by_role('button',name='Test',exact=True).click()
            setup.get_by_role('button',name='Save',exact=True).click()
            playwright.expect(setup.get_by_role('status')).to_have_text('Saved · Connected')
            setup.get_by_role('button',name='Enable connector').click()
            playwright.expect(github.get_by_role('switch',name='Enable GitHub')).to_be_checked()
            github.get_by_role('switch',name='Enable GitHub').press('Space')
            playwright.expect(github.get_by_role('switch')).not_to_be_checked()
            github.get_by_role('switch',name='Enable GitHub').click()
            playwright.expect(github.get_by_role('switch')).to_be_checked()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(tmp_path/f'integrations-{width}.png'))
            connector_tab.focus();connector_tab.press('ArrowRight')
            playwright.expect(workflow_tab).to_be_focused()
            playwright.expect(workflow_tab).to_have_attribute('aria-selected','true')
            playwright.expect(page.locator('#connector-integrations')).to_be_hidden()
            page.get_by_label('Find a workflow integration').fill('github')
            playwright.expect(page.locator('[data-app-key="github"]')).to_be_visible()
            assert page.locator('[data-app-key]:visible').evaluate_all("cards=>cards.every(card=>(card.textContent+' '+card.dataset.appDescription).toLowerCase().includes('github'))")
            assert page.locator('[data-app-key][hidden]').count()>0
            workflow_tab.press('Home')
            playwright.expect(connector_tab).to_be_focused()
            connector_tab.press('End')
            playwright.expect(page.get_by_label('Find a workflow integration')).to_have_value('github')
            page.goto('https://integrations.test/hfl-corpus/actions')
            action=page.locator('[data-followup-id="'+item['id']+'"]')
            with page.expect_response('**/integrations/api/actions/'+item['id']) as reply:
                action.get_by_role('button',name='Integrations',exact=True).click()
            assert reply.value.status==200,reply.value.text()
            modal=page.locator('.integration-dialog[open]')
            assert 'github' in reply.value.json(),reply.value.text()
            modal.get_by_label('Repository',exact=True).select_option('alice/demo')
            modal.get_by_label('Branch',exact=True).fill('feature/browser')
            modal.get_by_role('button',name='Create branch',exact=True).click()
            modal.get_by_role('button',name='Link PR / create draft PR',exact=True).click()
            playwright.expect(modal.get_by_role('link',name='PR #1',exact=True)).to_be_visible()
            assert connectors['pulls'][0]['draft']
            modal.get_by_role('button',name='Close',exact=True).click()
            connect(authenticated_client,'jira')
            page.goto('https://integrations.test/applications')
            page.get_by_role('button',name='Import assigned issues').click()
            modal=page.locator('.integration-dialog[open]')
            modal.get_by_label('Project',exact=True).select_option('TEST')
            modal.get_by_role('button',name='Import / refresh',exact=True).click()
            playwright.expect(modal.get_by_role('status')).to_have_text('1 issues imported or refreshed.')
            page.goto('https://integrations.test/hfl-corpus/actions')
            imported=page.locator('[data-followup-id]').filter(has=page.get_by_text('TEST-1 · Ship connected work',exact=True))
            imported.get_by_role('button',name='Integrations',exact=True).click()
            modal=page.locator('.integration-dialog[open]')
            modal.get_by_label('Jira transition',exact=True).select_option('2')
            modal.get_by_role('button',name='Update Jira status',exact=True).click()
            playwright.expect(modal.get_by_role('link',name='TEST-1 · In Progress',exact=True)).to_be_visible()
            assert connectors['status']=='2'
            bounds=modal.bounding_box()
            assert bounds['x']+bounds['width']/2==pytest.approx(width/2,abs=2)
            page.screenshot(path=str(tmp_path/f'integrations-jira-{width}.png'),full_page=True)
            page.goto('https://integrations.test/applications')
            page.goto('https://integrations.test/applications#workflow-integrations')
            playwright.expect(page.get_by_role('tab',name='Workflows')).to_have_attribute('aria-selected','true')
            page.get_by_role('button',name='Add application',exact=True).click()
            modal=page.locator('.integration-dialog[open]')
            modal.get_by_label('App name',exact=True).fill('browser_new_app')
            modal.get_by_label('Initial README description',exact=True).fill('Read application data')
            modal.get_by_role('button',name='Prepare Hermes workspace',exact=True).click()
            page.wait_for_url('**/hfl-corpus/actions?integration_agent=*')
            playwright.expect(page.locator('.action-agent-dialog[open]')).to_be_visible()
            playwright.expect(page.get_by_role('heading',name='Ready to work on this action?',exact=True)).to_be_visible()
            from modules.hfl_corpus.action_agents import store as terminals
            assert terminals().sessions()==[]
            assert not errors,errors
        finally:browser.close()


def test_provider_errors_are_redacted_and_redirects_not_followed(monkeypatch):
    import httpx
    original=httpx.Client
    requests=[]
    def respond(request):
        requests.append(request)
        return httpx.Response(403,json={'message':'echo private-token'},request=request)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return original(**kwargs,transport=httpx.MockTransport(respond))
    monkeypatch.setattr(httpx,'Client',client)
    with pytest.raises(HTTPException) as error:
        providers.Provider('github',{'token':'private-token'}).test()
    assert 'private-token' not in error.value.detail
    assert str(requests[0].url)=='https://api.github.com/user'
    assert requests[0].headers['authorization']=='Bearer private-token'


def test_jira_read_is_non_mutating_and_refresh_requires_csrf(connectors,authenticated_client):
    c=authenticated_client;connect(c,'jira')
    item=post(c,'/jira/import',{'project':'TEST'}).json()['items'][0]
    connectors['status']='3'
    root='/actions/'+item['id']+'/jira'
    assert c.get(BASE+root).json()['issue']['fields']['status']['name']=='Done'
    assert service.action(item['id'])['status']=='active'
    assert c.post(BASE+root+'/refresh',json={}).status_code==403
    assert post(c,root+'/refresh').json()['item']['status']=='done'


@pytest.mark.parametrize('provider',['github','jira'])
def test_credential_test_does_not_save_and_failed_save_preserves_connection(connectors,authenticated_client,provider):
    raw={'token':'test','site':'https://example.atlassian.net','email':'a@b.com'}
    assert post(authenticated_client,'/connectors/'+provider+'/test',raw).status_code==200
    assert store.get(USER,provider,private=True)['credentials']=={}
    connect(authenticated_client,provider)
    before=store.get(USER,provider,private=True)
    assert post(authenticated_client,'/connectors/'+provider+'/test',raw).status_code==200
    assert store.get(USER,provider,private=True)==before
    connectors['fail']=True
    for operation in ['test','save']:
        assert post(authenticated_client,'/connectors/'+provider+'/'+operation,raw).status_code==401
        assert store.get(USER,provider,private=True)==before
