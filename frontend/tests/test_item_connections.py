import json
from uuid import uuid4
from urllib.parse import urlparse

import pytest
from test_hfl_ideas import ideas, BASE, payload


def test_manual_idea_prefix_and_legacy_retry(ideas, authenticated_client):
    raw = payload(description='', body='Keep books')
    item = ideas.save_idea(raw, 'owner')
    assert item['id'].startswith('item-')
    assert ideas.save_idea(raw, 'owner')['id'] == item['id']
    legacy = 'idea-' + raw['request_id']
    with ideas.followups.connect() as db:
        item['id'] = legacy
        db.execute('UPDATE idea_edits SET id=?,payload=? WHERE id=?', (legacy,json.dumps(item),'item-'+raw['request_id']))
        db.execute('UPDATE idea_history SET id=?,payload=? WHERE id=?', (legacy,json.dumps(item),'item-'+raw['request_id']))
    assert ideas.save_idea(raw, 'owner')['id'] == legacy
    assert authenticated_client.get(BASE+'/item-connection-options', params={'query':legacy}).json()['nodes'][0]['object_id'] == legacy
    assert ideas.save_idea({'version':1,'title':'Updated'}, 'owner', legacy)['id'] == legacy


@pytest.mark.parametrize('relation', ['related-to','depends-on','blocked-by','cloned-from','promoted-from','created-from'])
def test_shared_connection_lifecycle_and_stale_edits(ideas, authenticated_client, relation):
    idea = ideas.save_idea(payload(), 'owner')
    action = ideas.followups.create({'request_id':str(uuid4()),'title':'Read books'},actor='owner')[0]
    edge = {'source':'idea:'+idea['id'],'target':'action:'+action['id'],'relation':relation}
    client = authenticated_client
    uri = BASE+'/item-connections'
    assert client.post(uri,json={'operation':'create','edge':edge}).status_code == 200
    assert client.post(uri,json={'operation':'create','edge':edge}).status_code == 422
    for kind, item in [('ideas',idea),('actions',action)]:
        graph = client.get(BASE+f'/{kind}/{item["id"]}/connections').json()
        assert any(e['source']==edge['source'] and e['target']==edge['target'] and e['relation']==relation for e in graph['edges'])
    saved = ideas.links()[0]
    replacement = {**edge,'source':edge['target'],'target':edge['source']}
    assert client.post(uri,json={'operation':'update','edge':edge,'revision':saved['revision'],'replacement':replacement}).status_code == 200
    assert client.post(uri,json={'operation':'remove','edge':replacement,'revision':saved['revision']}).status_code == 409
    assert client.post(uri,json={'operation':'remove','edge':replacement,'revision':ideas.links()[0]['revision']}).status_code == 200
    assert ideas.links() == []
    assert ideas.maps() == []


def test_generated_idea_ids_preserve_legacy_refresh(ideas):
    store = ideas.followups
    day = '2026-10-13'
    suggestion = {'category':'recommendations','title':'Read together','evidence':[]}
    run = store.claim_period(day,day)
    store.save_suggestions(day,day,run,[suggestion],{})
    item = store.suggestions(day,day)[0]
    assert item['id'].startswith('item-')
    legacy = 'suggestion-' + item['id'].removeprefix('item-')
    with store.connect() as db:
        db.execute('DELETE FROM timeline_suggestion_periods')
        item['id'] = legacy
        db.execute('UPDATE timeline_suggestions SET id=?,payload=?,status=?', (legacy,json.dumps(item),'dismissed'))
    run = store.claim_period(day,day,force=True)
    store.save_suggestions(day,day,run,[suggestion],{})
    assert store.suggestion(legacy)['status'] == 'dismissed'
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM timeline_suggestions').fetchone()[0] == 1


def test_promoted_idea_ids_and_legacy_receipts(ideas):
    from test_hfl_boards import board_payload
    board = ideas.save_map(board_payload())
    promoted = ideas.promote_draft(board['id'],'draft:seed',board['version'],'owner')
    assert promoted['idea_id'].startswith('item-')
    assert ideas.promote_draft(board['id'],'draft:seed',board['version'],'owner')['idea_id'] == promoted['idea_id']
    with ideas.followups.connect() as db:
        db.execute('UPDATE board_promotions SET idea_id=?', ('idea-legacy',))
    assert ideas.promote_draft(board['id'],'draft:seed',board['version'],'owner')['idea_id'] == 'idea-legacy'


def test_connections_reject_self_derived_and_protected_targets(ideas, authenticated_client):
    idea = ideas.save_idea(payload(), 'owner')
    hidden = ideas.save_idea(payload(title='Private',source={'path':'private.md','entry_id':'secret'}), 'owner')
    root = 'idea:'+idea['id']
    for target, relation, status in [(root,'related-to',422),('idea:'+hidden['id'],'depends-on',404),(root,'develops-into',422),([],'related-to',404)]:
        assert authenticated_client.post(BASE+'/item-connections',json={'operation':'create','edge':{'source':root,'target':target,'relation':relation}}).status_code == status
    assert authenticated_client.get(BASE+'/item-connection-options',params={'query':'Private'}).json()['nodes'] == []
    result = authenticated_client.get(BASE+'/item-connection-options',params={'query':idea['id']}).json()
    assert result['nodes'][0]['object_id'] == idea['id']


@pytest.mark.parametrize('width', [390, 1200])
@pytest.mark.parametrize('kind', ['action', 'idea'])
def test_editor_connections_sidebar_add_edit_remove(ideas, authenticated_client, monkeypatch, tmp_path, width, kind):
    from modules.hfl_corpus import router
    playwright = pytest.importorskip('playwright.sync_api')
    monkeypatch.setattr(router.corpus_index,'documents',lambda:())
    idea = ideas.save_idea(payload(title='A reading room'), 'owner')
    ideas.save_idea(payload(title='Compare reading room layouts with quiet areas and accessible shelves', description='', body='Explore comfortable layouts and lighting. ' * 30), 'owner')
    action = ideas.followups.create({'request_id':str(uuid4()),'title':'Read books'},actor='owner')[0]
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome',headless=True)
        page = browser.new_page(viewport={'width':width,'height':1000})
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        def route(intercept):
            request=intercept.request
            url=urlparse(request.url)
            if url.hostname != 'connections.test':
                intercept.abort();return
            response=authenticated_client.request(request.method,url.path+('?' + url.query if url.query else ''),content=request.post_data,headers={k:v for k,v in request.headers.items() if k.lower() in {'content-type','x-csrf-token'}})
            intercept.fulfill(status=response.status_code,body=response.content,headers={'content-type':response.headers.get('content-type','text/html')})
        page.route('**/*',route)
        if kind == 'action':
            page.goto('https://connections.test/hfl-corpus/actions')
            page.locator('[data-followup-id="'+action['id']+'"]').get_by_role('button',name='Edit',exact=True).click()
        else:
            page.goto('https://connections.test/hfl-corpus/graph?edit_kind=idea&edit='+idea['id'])
        editor=page.locator('dialog.has-connections-sidebar[open]')
        playwright.expect(editor).to_be_visible()
        sidebar=editor.locator('.item-connections-sidebar')
        assert sidebar.locator('details').get_attribute('open') is None
        sidebar.locator('summary').get_by_role('button',name='Add',exact=True).click()
        picker=page.locator('.connection-picker-dialog')
        playwright.expect(picker).to_be_visible()
        assert sidebar.locator('details').get_attribute('open') is not None
        playwright.expect(picker.locator('.idea-attach-choice').first).to_be_visible()
        cards=picker.locator('.idea-attach-choice')
        assert cards.first.locator('.connection-type-pill').count() == 1
        assert cards.first.locator('.connection-status-pill').count() == 1
        assert cards.first.locator('.connection-card-description').count() == 1
        assert cards.count() >= 2
        assert abs(cards.nth(0).bounding_box()['height']-cards.nth(1).bounding_box()['height']) < 1
        assert picker.evaluate('(el)=>el.scrollWidth <= el.clientWidth+1')
        search=picker.get_by_label('Search ideas and actions').bounding_box()
        select=picker.get_by_label('Connection type').bounding_box()
        assert abs(search['y']-select['y']) < 2
        assert search['x']+search['width'] < select['x']
        page.screenshot(path=str(tmp_path/f'picker-{width}.png'),full_page=True)
        picker.get_by_label('Search ideas and actions').fill(idea['id'] if kind=='action' else 'Read books')
        picker.get_by_role('button',name='A reading room' if kind=='action' else 'Read books',exact=False).click()
        picker.get_by_label('Search ideas and actions').fill('no matching item here')
        playwright.expect(picker.locator('.idea-choices')).to_contain_text('No matching')
        playwright.expect(picker.locator('.connection-selected')).to_contain_text('A reading room' if kind=='action' else 'Read books')
        picker.get_by_label('Connection type').select_option(label='depends on')
        picker.get_by_role('button',name='Save connection').click()
        playwright.expect(picker).to_have_count(0)
        playwright.expect(sidebar.get_by_role('button',name='Edit connection')).to_have_count(1)
        sidebar.get_by_role('button',name='Edit connection').click()
        picker.get_by_label('Connection type').select_option(label='blocks')
        picker.get_by_role('button',name='Save connection').click()
        playwright.expect(sidebar.locator('.connections-relations')).to_contain_text('blocks')
        canvas=sidebar.locator('.connections-canvas').bounding_box()
        details=sidebar.locator('.connections-details').bounding_box()
        assert details['y'] >= canvas['y']+canvas['height']-1
        assert editor.evaluate('(el)=>el.scrollWidth <= el.clientWidth+1')
        page.screenshot(path=str(tmp_path/f'connections-{width}.png'),full_page=True)
        sidebar.get_by_role('button',name='Edit connection').click()
        picker.get_by_role('button',name='Remove connection').click()
        playwright.expect(sidebar.get_by_role('button',name='Edit connection')).to_have_count(0)
        sidebar.locator('summary').focus()
        page.keyboard.press('Enter')
        playwright.expect(sidebar.locator('canvas')).to_have_count(0)
        assert ideas.links()==[]
        assert not errors
        browser.close()
