"""Experimental discovery contracts: no live credentials or remote Bot writes."""
import base64
import json
import logging
import time
from uuid import uuid4
from urllib.parse import urlparse, parse_qs

import httpx
import pytest
from fastapi import HTTPException
from frontend.tests.test_agent_fleet import fleet, bridge
from frontend.tests.test_hfl_agent_bridge import owner_headers

USER = 'frontend-test-user'
BOT = str(uuid4())


def pair(sub='account-one', exp=None):
    payload = base64.urlsafe_b64encode(json.dumps({'sub':sub,'exp':exp or time.time()+3600}).encode()).decode().rstrip('=')
    return {'accessToken':'header.'+payload+'.private-signature', 'refreshToken':'private-refresh-'+sub}


def remote(identity=BOT, name='Research Bot'):
    return {'agentId':identity, 'kind':'GROK_BOT_AGENT_KIND_AGENT', 'name':name, 'description':'Find evidence'}


@pytest.fixture
def grok(fleet, monkeypatch):
    from modules.integrations import grokbot as g
    state = {'pair':pair(), 'rows':[remote()], 'calls':[], 'fail':None}
    def request(path, **kw):
        state['calls'].append((path, kw))
        if state['fail'] and path.endswith('ListGrokBotAgents'):
            raise HTTPException(*state['fail'])
        if path.endswith('ListGrokBotAgents'):
            return {'agents':state['rows']}
        if path == '/oauth/token':
            return {'access_token':state['pair']['accessToken'], 'refresh_token':state['pair']['refreshToken']}
        return state['pair']
    monkeypatch.setattr(g, 'request', request)
    return g, state


def post(client, path, data=None):
    return client.post('/integrations/api'+path,json=data or {},headers=owner_headers())


def bots(fleet):
    return [a for a in fleet.store().list() if a['runtime']=='grokbot']


def test_key_connect_discovers_and_encrypts(grok, fleet, authenticated_client):
    g, state = grok
    result = post(authenticated_client,'/grokbot/connect-key',{'key':'cursor-user-secret'})
    assert result.status_code == 200 and result.json()['imported'] == 1
    assert bots(fleet)[0]['name'] == 'Research Bot'
    saved = g.store.get(USER,'grokbot',private=True)
    assert saved['enabled'] and saved['credentials'] == state['pair']
    with g.store.connection() as db:
        raw = db.execute('SELECT credentials,metadata FROM connectors').fetchone()
    assert 'private-refresh' not in str(tuple(raw)) and 'cursor-user-secret' not in str(tuple(raw))
    public = authenticated_client.get('/integrations/api/connectors').text
    assert state['pair']['accessToken'] not in public and 'private-refresh' not in public
    listing = authenticated_client.get('/agents/api/items').json()['items']
    assert next(a for a in listing if a['runtime']=='grokbot')['state']=='Discovered'


def test_browser_pkce_poll_and_cancel(grok, authenticated_client):
    g, state = grok
    start = post(authenticated_client,'/grokbot/login/start').json()
    query = parse_qs(urlparse(start['url']).query)
    assert query['uuid'] == [start['attempt_id']] and 'verifier' not in query
    assert 'verifier' not in start
    assert post(authenticated_client,'/grokbot/login/wrong/poll').status_code == 410
    assert post(authenticated_client,'/grokbot/login/'+start['attempt_id']+'/poll').json()['imported']==1
    assert post(authenticated_client,'/grokbot/login/'+start['attempt_id']+'/poll').status_code==410
    pending = post(authenticated_client,'/grokbot/login/start').json()
    assert post(authenticated_client,'/grokbot/login/'+pending['attempt_id']+'/cancel').status_code==200
    assert post(authenticated_client,'/grokbot/login/'+pending['attempt_id']+'/poll').status_code==410
    assert g.store.get(USER,'grokbot')['enabled']


def test_browser_expiry_isolation_and_stale_attempt(grok):
    g, state = grok
    first = g.start_login(USER)
    second = g.start_login(USER)
    with pytest.raises(HTTPException) as exc:
        g.poll_login(USER, first['attempt_id'])
    assert exc.value.status_code==410
    with pytest.raises(HTTPException):
        g.poll_login('other',second['attempt_id'])
    g.cancel(USER,first['attempt_id'])
    with g.store.connection() as db:
        assert db.execute('SELECT identity FROM grokbot_login').fetchone()[0]==second['attempt_id']
        db.execute('UPDATE grokbot_login SET expires=0')
    with pytest.raises(HTTPException):
        g.poll_login(USER,second['attempt_id'])


def test_one_shot_browser_tokens_survive_roster_retry(grok):
    g, state = grok
    start = g.start_login(USER)
    state['fail'] = (502, 'Temporary roster failure')
    with pytest.raises(HTTPException):
        g.poll_login(USER, start['attempt_id'])
    with g.store.connection() as db:
        row = db.execute('SELECT payload FROM grokbot_login WHERE user=?', (USER,)).fetchone()
        saved = json.loads(g.store.cipher(USER, 'grokbot').decrypt(row[0].encode()))
        assert saved['pair'] == state['pair']
        saved['next_poll'] = 0
        encrypted = g.store.cipher(USER, 'grokbot').encrypt(json.dumps(saved).encode()).decode()
        db.execute('UPDATE grokbot_login SET payload=? WHERE user=?', (encrypted, USER))
    state['fail'] = None
    assert g.poll_login(USER, start['attempt_id'])['imported'] == 1
    assert sum(path == '/auth/poll' for path, _ in state['calls']) == 1


def test_cancel_during_upstream_poll_cannot_save_credentials(grok, monkeypatch):
    g, state = grok
    start = g.start_login(USER)
    upstream = g.request
    def request(path, **kwargs):
        if path == '/auth/poll':
            g.cancel(USER, start['attempt_id'])
        return upstream(path, **kwargs)
    monkeypatch.setattr(g, 'request', request)
    with pytest.raises(HTTPException) as exc:
        g.poll_login(USER, start['attempt_id'])
    assert exc.value.status_code == 410
    assert not g.store.get(USER, 'grokbot', private=True)['credentials']


def test_reconcile_rename_override_missing_and_return(grok, fleet):
    g, state = grok
    g.connect_key(USER,'key')
    original = bots(fleet)[0]
    customized = {**original,'color':'#123456','workspace_ids':['work']}
    fleet.store().save(customized,identity=original['id'],version=original['version'])
    state['rows'] = [remote(name='Renamed')]
    g.sync(USER)
    renamed = bots(fleet)[0]
    assert renamed['id']==original['id'] and renamed['name']=='Renamed'
    assert renamed['color']=='#123456' and renamed['workspace_ids']==['work']
    fleet.store().save({**renamed,'name':'Local name'},identity=renamed['id'],version=renamed['version'])
    state['rows'] = [remote(name='Another name')]
    g.sync(USER)
    assert bots(fleet)[0]['name']=='Local name'
    state['rows'] = []
    g.sync(USER)
    assert not bots(fleet)[0]['remote_available'] and bots(fleet)[0]['active']
    state['rows'] = [remote()]
    g.sync(USER)
    assert bots(fleet)[0]['remote_available'] and bots(fleet)[0]['name']=='Local name'


def test_failure_preserves_roster_and_connection_replacement(grok, fleet):
    g, state = grok
    g.connect_key(USER,'key')
    old = bots(fleet)
    state['pair'] = pair('other-account')
    state['fail'] = (502,'Temporary failure')
    with pytest.raises(HTTPException):
        g.connect_key(USER,'replacement')
    assert g.store.get(USER,'grokbot')['account_id']==g.account_id(pair())
    assert bots(fleet)==old
    with pytest.raises(HTTPException):
        g.sync(USER)
    assert bots(fleet)==old
    state['fail'] = (401,'Reconnect')
    with pytest.raises(HTTPException):
        g.sync(USER)
    assert g.store.get(USER,'grokbot')['status']=='Reconnect required'


def test_account_switch_disconnect_and_visibility(grok, fleet):
    from modules.agents.projection import listing
    g, state = grok
    g.connect_key(USER,'key')
    old_id = bots(fleet)[0]['id']
    assert not any(a['runtime']=='grokbot' for a in listing('other'))
    state['pair'] = pair('second')
    g.connect_key(USER,'key')
    assert len(bots(fleet))==2
    assert old_id not in [a['id'] for a in listing(USER)]
    g.disconnect(USER)
    assert not any(a['runtime']=='grokbot' for a in listing(USER))
    assert len(bots(fleet))==2
    assert g.store.get(USER,'grokbot',private=True)['credentials']=={}


def test_refresh_rotation_saved_even_if_roster_fails(grok):
    g, state = grok
    state['pair'] = pair(exp=time.time()-100)
    g.connect_key(USER,'key')
    state['pair'] = {**pair(), 'refreshToken':'rotated-private-token'}
    state['fail'] = (502,'Temporary failure')
    with pytest.raises(HTTPException):
        g.sync(USER)
    assert g.store.get(USER,'grokbot',private=True)['credentials']==state['pair']


def test_throttle_lock_and_remote_settings(grok, fleet, authenticated_client):
    g, state = grok
    g.connect_key(USER,'key')
    count = len(state['calls'])
    assert g.sync(USER,True)['status']=='cached' and len(state['calls'])==count
    with g.locked(USER):
        with pytest.raises(HTTPException) as exc:
            g.disconnect(USER)
        assert exc.value.status_code==409
    item = bots(fleet)[0]
    result = authenticated_client.post('/agents/api/items/'+item['id'],json={'version':item['version'],'instructions':'execute'},headers=owner_headers())
    assert result.status_code==422
    assert authenticated_client.post('/integrations/api/grokbot/connect-key',json={'key':'key'}).status_code==403
    assert post(authenticated_client,'/connectors/grokbot/test',{'token':'key'}).status_code==409


def test_bad_roster_does_not_mark_missing(grok, fleet):
    g, state = grok
    g.connect_key(USER,'key')
    state['rows'] = [remote(), {'kind':'unexpected'}]
    with pytest.raises(HTTPException):
        g.sync(USER)
    assert bots(fleet)[0]['remote_available']


def test_wire_protocol_pending_and_secret_log_redaction(fleet, monkeypatch, caplog):
    from modules.integrations import grokbot as g
    client_type = httpx.Client
    requests=[]
    def respond(req):
        requests.append(req)
        if req.url.path=='/auth/poll':
            assert req.url.params['verifier']=='private-verifier'
            return httpx.Response(404)
        assert req.headers['authorization']=='Bearer private-key'
        return httpx.Response(200,json=pair())
    monkeypatch.setattr(httpx,'Client',lambda **kw: client_type(transport=httpx.MockTransport(respond)))
    caplog.set_level(logging.INFO,logger='httpx')
    assert g.request('/auth/poll',method='GET',params={'uuid':'id','verifier':'private-verifier'},pending=True) is None
    assert g.token_pair(g.request('/auth/exchange_user_api_key',token='private-key',payload={}))['accessToken']
    assert 'private-verifier' not in caplog.text and 'private-key' not in caplog.text
    assert all(r.url.host=='api2.cursor.sh' for r in requests)


def test_browser_connection_ui(grok, authenticated_client, tmp_path, monkeypatch):
    playwright = pytest.importorskip('playwright.sync_api')
    errors=[]
    with playwright.sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror',lambda e:errors.append(str(e)))
        def route(r):
            u=urlparse(r.request.url)
            response=authenticated_client.request(r.request.method,u.path+('?' + u.query if u.query else ''),content=r.request.post_data_buffer,
                headers={k:v for k,v in r.request.headers.items() if k.lower() in {'content-type','x-csrf-token'}})
            r.fulfill(status=response.status_code,content_type=response.headers.get('content-type','text/html'),body=response.content)
        page.route('https://grok.test/**',route)
        page.goto('https://grok.test/applications')
        card=page.locator('.connector-card').filter(has=page.get_by_role('heading',name='Grok Bot',exact=True))
        card.get_by_role('button',name='Connect',exact=True).click()
        dialog=page.get_by_role('dialog',name='Connect Grok Bot')
        g, state = grok
        state['fail'] = (502, 'Temporary roster failure')
        dialog.get_by_role('button',name='Sign in with browser',exact=True).click()
        retry = dialog.get_by_role('button',name='Check sign-in again',exact=True)
        retry.wait_for(timeout=15000)
        with monkeypatch.context() as patch:
            def busy_login(user):
                raise HTTPException(409, 'Grok Bot connection is busy.')
            patch.setattr(g, 'start_login', busy_login)
            dialog.get_by_role('button',name='Sign in with browser',exact=True).click()
            playwright.expect(dialog.get_by_role('alert')).to_have_text('Grok Bot connection is busy.')
            playwright.expect(retry).not_to_be_visible()
        state['fail'] = None
        dialog.get_by_role('button',name='Sign in with browser',exact=True).click()
        dialog.get_by_role('link',name='Continue on Cursor').wait_for()
        assert dialog.get_by_role('link',name='Continue on Cursor').get_attribute('href').startswith('https://cursor.com/loginDeepControl?')
        playwright.expect(dialog).not_to_be_visible(timeout=15000)
        card.get_by_role('button',name='Reconnect',exact=True).click()
        dialog=page.get_by_role('dialog',name='Connect Grok Bot')
        dialog.locator('summary').click()
        dialog.get_by_label('Cursor API key',exact=True).fill('test-key')
        page.screenshot(path=str(tmp_path/'grokbot-desktop.png'))
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path=str(tmp_path/'grokbot-mobile.png'))
        assert dialog.evaluate('(el)=>el.scrollWidth<=el.clientWidth')
        dialog.get_by_role('button',name='Connect with API key',exact=True).click()
        playwright.expect(dialog).not_to_be_visible()
        page.goto('https://grok.test/agents')
        page.get_by_role('button',name='Select Research Bot',exact=True).click()
        page.get_by_role('button',name='Open Grok Bot',exact=True).wait_for()
        assert not errors
        browser.close()
