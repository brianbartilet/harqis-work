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
        if path == '/repos/alice/demo/branches':
            start=(params.get('page',1)-1)*params.get('per_page',50)
            return [{'name':b} for b in list(state['branches'])[start:start+params.get('per_page',50)]]
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


def test_github_branch_picker_pagination(connectors,authenticated_client):
    c=authenticated_client;connect(c,'github')
    connectors['branches'].update({f'feature/{i}':'abc' for i in range(55)})
    first=c.get(BASE+'/github/branches',params={'repository_name':'alice/demo'}).json()
    second=c.get(BASE+'/github/branches',params={'repository_name':'alice/demo','page':2}).json()
    assert len(first['items'])==50 and first['more']
    assert len(second['items'])==6 and not second['more']
    assert len(set(first['items']+second['items']))==56
    assert c.get(BASE+'/github/branches',params={'repository_name':'alice/demo','page':0}).status_code==422
    assert not any('/pulls' in call[2] for call in connectors['calls'])


def test_github_pull_request_picker_filters_source(connectors,authenticated_client):
    c=authenticated_client;connect(c,'github')
    def pull(number,repo,head):
        return {'number':number,'title':'Change '+str(number),'state':'open','draft':True,
                'head':{'ref':head,'repo':{'full_name':repo}}}
    connectors['pulls']=[pull(1,'alice/demo','feature/test'),pull(2,'alice/demo','other'),pull(3,'fork/demo','feature/test')]
    response=c.get(BASE+'/github/pulls',params={'repository_name':'alice/demo','branch_name':'feature/test'})
    assert response.status_code==200
    assert response.json()=={'items':[{'number':1,'title':'Change 1','state':'open','draft':True}],'more':False}
    assert c.get(BASE+'/github/pulls',params={'repository_name':'alice/demo','branch_name':'feature/test','page':0}).status_code==422


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


def test_clear_github_settings_is_scoped_and_keeps_remote_resources(connectors,authenticated_client):
    c=authenticated_client;connect(c,'github');item=card(c)
    root='/actions/'+item['id']+'/github'
    branch={'repository':'alice/demo','branch':'feature/clear','base':'main','operation':'create-branch'}
    assert post(c,root+'/branch',branch).status_code==200
    linked=c.get(BASE+root).json()['items'][0]
    assert post(c,root+'/pr',{'resource':linked['resource']}).status_code==200
    assert post(c,root+'/branch',{**branch,'branch':'feature/second'}).status_code==200
    account=service.account_key(store.get(USER,'github'))
    preserved=[(USER,'github','other-action',{'action_id':'other','account_key':account}),
               (USER,'jira','jira-link',{'action_id':item['id'],'account_key':account}),
               ('another-user','github','another-user-link',{'action_id':item['id'],'account_key':account}),
               (USER,'github','other-account',{'action_id':item['id'],'account_key':'other-account'})]
    for user,provider,resource,payload in preserved:store.link(user,provider,resource,payload)
    credentials=store.get(USER,'github',private=True)
    calls=list(connectors['calls'])
    assert c.post(BASE+root+'/clear',json={}).status_code==403
    assert post(c,'/actions/missing/github/clear').status_code==404
    assert len(service.visible_links(USER,'github'))==3
    result=post(c,root+'/clear')
    assert result.status_code==200 and result.json()=={'removed':2}
    assert post(c,root+'/clear').json()=={'removed':0}
    assert connectors['calls']==calls
    assert 'feature/clear' in connectors['branches'] and len(connectors['pulls'])==1
    assert store.get(USER,'github',private=True)==credentials
    for user,provider,resource,_ in preserved:
        assert resource in {link['resource'] for link in store.links(user,provider)}
    assert c.get(BASE+root).json()=={'items':[]}


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
    connectors['branches'].update({f'feature/page-{i}':'abc' for i in range(55)})
    connectors['branches']['release/test']='release-sha'
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
            agent_tab=page.get_by_role('tab',name='Agents')
            playwright.expect(agent_tab).to_have_attribute('aria-selected','true')
            connector_tab.click()
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
            playwright.expect(agent_tab).to_be_focused()
            connector_tab.press('End')
            playwright.expect(page.get_by_label('Find a workflow integration')).to_have_value('github')
            page.goto('https://integrations.test/hfl-corpus/actions')
            action=page.locator('[data-followup-id="'+item['id']+'"]')
            action.get_by_role('button',name='Edit',exact=True).click()
            editor=page.locator('#followup-editor')
            settings=editor.locator('.github-action-section')
            playwright.expect(settings.locator('summary')).to_have_text('Repository settings')
            summaries=editor.locator('.item-connections-sidebar > details > summary, .item-connections-sidebar > div > details > summary')
            heights=summaries.evaluate_all('items=>items.map(item=>item.getBoundingClientRect().height)')
            assert len(heights)==3 and max(heights)-min(heights)<2,heights
            assert summaries.evaluate_all('items=>items.map(item=>item.firstChild.textContent)')==['Connections','Agent settings','Repository settings']
            connections=editor.locator('.item-connections-sidebar > div > details')
            assert connections.locator('summary button').count()==0
            connections.locator('summary').click()
            playwright.expect(connections.locator('.connections-canvas canvas')).to_be_visible()
            add=connections.get_by_role('button',name='Add',exact=True)
            graph_bounds=connections.locator('.connections-canvas').bounding_box()
            add_bounds=add.bounding_box()
            assert graph_bounds['x']<=add_bounds['x']<graph_bounds['x']+graph_bounds['width']/2
            assert graph_bounds['y']<=add_bounds['y']<graph_bounds['y']+50
            tools_bounds=connections.locator('.connections-tools').bounding_box()
            assert add_bounds['x']+add_bounds['width']<tools_bounds['x']
            add.click()
            picker=page.get_by_role('dialog',name='Add connection',exact=True)
            playwright.expect(picker).to_be_visible()
            picker.press('Escape')
            playwright.expect(add).to_be_focused()
            page.screenshot(path=str(tmp_path/f'connections-add-{width}.png'))
            connections.locator('summary').click()
            agent_settings=editor.locator('.item-connections-sidebar > [data-action-agent-settings]')
            playwright.expect(agent_settings).to_have_count(1)
            assert editor.locator('.agenda-form-body [data-action-agent-settings]').count()==0
            agent_settings.locator('summary').click()
            playwright.expect(agent_settings.locator('[data-agent-settings-summary]')).to_contain_text('Hermes')
            playwright.expect(agent_settings.get_by_role('link',name='Agent default settings')).to_be_visible()
            agent_settings.locator('summary').click()
            settings.locator('summary').click()
            provider_summary=settings.get_by_role('region',name='Github',exact=True)
            playwright.expect(provider_summary.get_by_role('heading',name='Github',exact=True)).to_be_visible()
            playwright.expect(provider_summary).to_contain_text('No GitHub repository or branch linked yet.')
            group_bounds=provider_summary.bounding_box()
            button_bounds=provider_summary.get_by_role('button',name='Settings').bounding_box()
            assert button_bounds['x']+button_bounds['width']/2==pytest.approx(group_bounds['x']+group_bounds['width']/2,abs=2)
            assert settings.locator('input,select,textarea').count()==0
            settings.get_by_role('button',name='Settings',exact=True).click()
            modal=page.get_by_role('dialog',name='Github settings',exact=True)
            initial_bounds=modal.bounding_box()
            modal.locator('.github-branch-picker > summary').click()
            collapsed_bounds=modal.bounding_box()
            for dimension in ('x','y','width','height'):
                assert collapsed_bounds[dimension]==pytest.approx(initial_bounds[dimension],abs=1)
            modal.locator('.github-branch-picker > summary').click()
            playwright.expect(modal.get_by_label('Branch',exact=True)).to_be_disabled()
            modal.get_by_label('Repository',exact=True).select_option('alice/demo')
            playwright.expect(modal.get_by_label('Existing branch',exact=True)).to_be_visible()
            playwright.expect(modal.get_by_label('Branch',exact=True)).not_to_be_visible()
            playwright.expect(modal.get_by_label('Base branch',exact=True)).not_to_be_visible()
            assert modal.get_by_role('button',name='Browse branches',exact=True).count()==0
            modal.get_by_label('Branch action',exact=True).select_option('create-branch')
            playwright.expect(modal.get_by_label('Existing branch',exact=True)).not_to_be_visible()
            playwright.expect(modal.get_by_label('Branch',exact=True)).to_be_visible()
            playwright.expect(modal.get_by_label('Base branch',exact=True)).to_be_visible()
            playwright.expect(modal.get_by_label('Base branch',exact=True)).to_have_value('main')
            base_picker=modal.get_by_role('combobox',name='Base branch',exact=True)
            base_picker.fill('no-such-branch')
            playwright.expect(modal.get_by_text('No matching branches.',exact=True)).to_be_visible()
            base_picker.press('Escape')
            playwright.expect(base_picker).to_have_value('main')
            playwright.expect(modal).to_be_visible()
            base_picker.fill('release/')
            playwright.expect(modal.get_by_role('option',name='release/test',exact=True)).to_be_visible()
            base_picker.press('ArrowDown');base_picker.press('Enter')
            playwright.expect(base_picker).to_have_value('release/test')
            assert modal.get_by_role('button',name='Load more branches',exact=True).count()==0
            assert modal.get_by_text('More branches are available. Load more if yours is missing.',exact=True).count()==0
            modal.get_by_label('Branch',exact=True).fill('feature/browser')
            page.screenshot(path=str(tmp_path/f'branch-selector-{width}.png'))
            modal.get_by_role('button',name='Save',exact=True).click()
            assert connectors['branches']['feature/browser']=='release-sha'
            playwright.expect(modal.get_by_label('Description',exact=True)).not_to_be_visible()
            modal.get_by_text('Add a pull request',exact=True).click()
            modal.get_by_label('Pull request action',exact=True).select_option('link')
            playwright.expect(modal.get_by_label('Description',exact=True)).not_to_be_visible()
            playwright.expect(modal.get_by_text('No pull requests found for this branch.',exact=True)).to_be_visible()
            modal.locator('details').filter(has=modal.get_by_label('Pull request action',exact=True)).get_by_role('button',name='Link',exact=True).click()
            assert connectors['pulls']==[]
            modal.get_by_label('Pull request action',exact=True).select_option('create')
            modal.get_by_label('Description',exact=True).fill('Browser test draft')
            modal.get_by_role('button',name='Publish pull request',exact=True).click()
            playwright.expect(modal.get_by_role('link',name='PR #1',exact=True)).to_be_visible()
            playwright.expect(modal.get_by_role('link',name='Review and publish on GitHub')).to_have_attribute('href','https://github.com/alice/demo/pull/1')
            assert connectors['pulls'][0]['draft']
            assert editor.locator('[data-connector-summary]').count()==0
            assert action.locator('[data-connector-summary]').count()==0
            assert modal.evaluate('el=>el.scrollWidth<=el.clientWidth')
            page.screenshot(path=str(tmp_path/f'github-settings-{width}.png'))
            modal.press('Escape')
            playwright.expect(settings.get_by_role('button',name='Settings')).to_be_focused()
            playwright.expect(provider_summary).to_contain_text('alice/demo')
            playwright.expect(provider_summary).to_contain_text('Target: release/test')
            playwright.expect(provider_summary.get_by_role('link',name='feature/browser',exact=True)).to_be_visible()
            playwright.expect(provider_summary.get_by_role('link',name='PR #1',exact=True)).to_be_visible()
            playwright.expect(provider_summary).to_contain_text('Draft')
            settings.get_by_role('button',name='Settings').click()
            playwright.expect(modal.get_by_role('link',name='PR #1',exact=True)).to_be_visible()
            modal.get_by_text('Link another branch',exact=True).click()
            modal.get_by_label('Repository',exact=True).select_option('alice/demo')
            modal.get_by_label('Branch action',exact=True).select_option('create-branch')
            modal.get_by_label('Branch',exact=True).fill('unsaved-branch')
            modal.get_by_role('button',name='Clear all settings',exact=True).click()
            playwright.expect(modal.get_by_role('status')).to_have_text('GitHub settings cleared for this action.')
            playwright.expect(modal.get_by_text('No branches linked yet.',exact=True)).to_be_visible()
            playwright.expect(modal.get_by_label('Repository',exact=True)).to_have_value('')
            playwright.expect(modal.get_by_label('Branch',exact=True)).to_have_value('')
            playwright.expect(modal.get_by_label('Base branch',exact=True)).to_have_value('')
            assert modal.locator('.connector-link').count()==0
            modal.get_by_role('button',name='Close',exact=True).click()
            playwright.expect(provider_summary).to_contain_text('No GitHub repository or branch linked yet.')
            settings.get_by_role('button',name='Settings').click()
            playwright.expect(modal.get_by_text('No branches linked yet.',exact=True)).to_be_visible()
            modal.get_by_label('Repository',exact=True).select_option('alice/demo')
            existing_picker=modal.get_by_role('combobox',name='Existing branch',exact=True)
            existing_picker.fill('browser')
            page.screenshot(path=str(tmp_path/f'branch-search-{width}.png'))
            modal.get_by_role('option',name='feature/browser',exact=True).click()
            playwright.expect(existing_picker).to_have_value('feature/browser')
            existing_picker.click()
            existing_picker.fill('unmatched-filter')
            modal.get_by_role('heading',name='Linked branches and pull requests').click()
            playwright.expect(existing_picker).to_have_value('feature/browser')
            playwright.expect(modal.get_by_label('Branch',exact=True)).not_to_be_visible()
            playwright.expect(modal.get_by_label('Base branch',exact=True)).not_to_be_visible()
            modal.get_by_role('button',name='Link',exact=True).click()
            modal.get_by_text('Add a pull request',exact=True).click()
            modal.get_by_label('Pull request action',exact=True).select_option('link')
            pr_picker=modal.get_by_role('combobox',name='Pull request',exact=True)
            pr_picker.fill('Ship integration')
            modal.get_by_role('option',name='#1 · Ship integration · Draft',exact=True).click()
            playwright.expect(pr_picker).to_have_value('#1 · Ship integration · Draft')
            modal.locator('details').filter(has=modal.get_by_label('Pull request action',exact=True)).get_by_role('button',name='Link',exact=True).click()
            playwright.expect(modal.get_by_role('link',name='PR #1',exact=True)).to_be_visible()
            assert len(connectors['pulls'])==1
            modal.get_by_role('button',name='Close',exact=True).click()
            page.screenshot(path=str(tmp_path/f'repository-settings-{width}.png'))
            editor.get_by_role('button',name='Close',exact=True).click()
            action.get_by_role('button',name='Edit',exact=True).click()
            playwright.expect(agent_settings).to_have_count(1)
            agent_settings.locator('summary').click()
            playwright.expect(agent_settings.locator('[data-agent-settings-summary]')).to_contain_text('Hermes')
            page.screenshot(path=str(tmp_path/f'agent-settings-{width}.png'))
            editor.get_by_role('button',name='Close',exact=True).click()
            connect(authenticated_client,'jira')
            page.goto('https://integrations.test/applications#connector-integrations')
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
