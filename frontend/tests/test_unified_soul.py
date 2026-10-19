"""Atomic unified Soul edits, conflicts and owner safeguards."""
import pytest
from test_entity_soul import soul_data
from workflows.hfl.entity_store import get_store


def draft(client):
    snapshot = client.get('/api/hfl/entities/soul-editor/brian')
    assert snapshot.status_code == 200, snapshot.text
    data = snapshot.json()
    soul = {k:v for k,v in data['soul'].items() if k in {'version','markdown','identity_rules','relationships','journal'}}
    for field in ('identity_rules','relationships','journal'):
        soul[field] = [{k:v for k,v in r.items() if k != 'provenance'} for r in soul[field]]
    return dict(revision=data['revision'],profile={'name':'Brian Bartilet','notes':'Updated profile'},soul={**soul,'markdown':'Updated identity'},connections={'versions':data['versions'],'changes':[{'id':'one','target_id':'company','relation':'works_at'}]})


def test_unified_save_and_stale_rejection(soul_data, authenticated_client):
    client=authenticated_client
    payload=draft(client)
    response=client.post('/api/hfl/entities/soul-editor/brian',json=payload)
    assert response.status_code == 200, response.text
    saved=client.get('/api/hfl/entities/soul-editor/brian').json()
    assert saved['entity']['profile']['notes']=='Updated profile'
    assert saved['soul']['markdown']=='Updated identity'
    assert saved['connections'][0]['target_id']=='company'
    assert client.post('/api/hfl/entities/soul-editor/brian',json=payload).status_code==409


def test_failure_rolls_back_profile_and_connections(soul_data, authenticated_client):
    client=authenticated_client;payload=draft(client)
    before=client.get('/api/hfl/entities/soul-editor/brian').json()
    payload['connections']['changes'].append({'id':'bad','target_id':'missing','relation':'related_to'})
    assert client.post('/api/hfl/entities/soul-editor/brian',json=payload).status_code==409
    after=client.get('/api/hfl/entities/soul-editor/brian').json()
    assert after['revision']==before['revision']
    assert after['soul']==before['soul']


def test_profile_conflict(soul_data, authenticated_client):
    payload=draft(authenticated_client)
    get_store().save_profile('brian','people',{'name':'Brian revised'})
    assert authenticated_client.post('/api/hfl/entities/soul-editor/brian',json=payload).status_code==409


def test_new_entity_created_only_with_successful_save(soul_data, authenticated_client):
    from uuid import uuid4
    client=authenticated_client;payload=draft(client);identity='manual-'+str(uuid4())
    payload['new_entities']=[{'id':identity,'name':'New team','kind':'companies'}]
    payload['connections']['changes'][0]['target_id']=identity
    payload['connections']['changes'].append({'id':'bad','target_id':'missing','relation':'related_to'})
    assert client.post('/api/hfl/entities/soul-editor/brian',json=payload).status_code==409
    assert identity not in get_store().profiles()
    payload['connections']['changes'].pop()
    result=client.post('/api/hfl/entities/soul-editor/brian',json=payload)
    assert result.status_code==200,result.text
    assert identity in get_store().profiles()


def test_soul_editor_requires_owner():
    from fastapi.testclient import TestClient
    from hfl_api import app
    client=TestClient(app)
    assert client.get('/api/hfl/entities/soul-editor/brian').status_code in (401,403)


def test_unified_dialog_unsaved_and_error_retention(soul_data, authenticated_client):
    from pathlib import Path
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as engine:
        browser=engine.chromium.launch(headless=True,**({} if Path(engine.chromium.executable_path).exists() else {'channel':'msedge'}))
        try:
            page=browser.new_page(viewport={'width':1440,'height':1000})
            def route_request(route):
                req=route.request
                if req.method=='POST' and '/soul-editor/' in req.url:
                    route.fulfill(status=409,json={'detail':'Entity details changed. Your edits are retained.'});return
                response=authenticated_client.request(req.method,req.url.replace('https://entities.test',''),content=req.post_data_buffer,headers={'content-type':'application/json'})
                route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-encoding','content-length'}})
            page.route('https://entities.test/**',route_request)
            page.goto('https://entities.test/hfl-corpus/entities')
            card=page.locator('[data-entity-id="brian"]');card.locator(':scope > summary').click()
            card.get_by_role('button',name='Update soul',exact=True).click()
            dialog=page.get_by_role('dialog',name='Brian Bartilet')
            playwright.expect(dialog.get_by_text('Identity matching helpers',exact=True)).to_be_visible()
            assert dialog.locator('form > details[open]').count()==0
            box=dialog.bounding_box();assert abs(box['x']+box['width']/2-720)<2
            page.screenshot(path='results/unified-soul-collapsed.png')
            dialog.get_by_text('Identity matching helpers',exact=True).click()
            dialog.get_by_label('Notes',exact=True).fill('Keep my unsaved notes')
            page.once('dialog',lambda prompt:prompt.dismiss())
            dialog.get_by_role('button',name='Close',exact=True).click()
            playwright.expect(dialog).to_be_visible()
            dialog.get_by_role('button',name='Save',exact=True).click()
            playwright.expect(dialog.get_by_text('Entity details changed. Your edits are retained.',exact=True)).to_be_visible()
            playwright.expect(dialog.get_by_label('Notes',exact=True)).to_have_value('Keep my unsaved notes')
            page.once('dialog',lambda prompt:prompt.accept())
            dialog.get_by_role('button',name='Close',exact=True).click()
            playwright.expect(dialog).to_have_count(0)
        finally:
            browser.close()


@pytest.mark.parametrize('width', [1440, 390])
def test_soul_layout_loading_and_help(soul_data, authenticated_client, width):
    from pathlib import Path
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as engine:
        browser = engine.chromium.launch(headless=True, **({} if Path(engine.chromium.executable_path).exists() else {'channel': 'msedge'}))
        try:
            page = browser.new_page(viewport={'width': width, 'height': 740})
            pending = []
            def serve(route):
                req = route.request
                response = authenticated_client.request(req.method, req.url.replace('https://entities.test', ''), content=req.post_data_buffer, headers={'content-type': 'application/json'})
                route.fulfill(status=response.status_code, body=response.content, headers={k: v for k, v in response.headers.items() if k.lower() not in {'content-encoding', 'content-length'}})
            def route_request(route):
                if '/soul-editor/' in route.request.url:
                    pending.append(route)
                else:
                    serve(route)
            page.route('https://entities.test/**', route_request)
            page.goto('https://entities.test/hfl-corpus/entities')
            card = page.locator('[data-entity-id="brian"]')
            card.locator(':scope > summary').click()
            card.get_by_role('button', name='Update soul', exact=True).click()
            dialog = page.get_by_role('dialog', name='Brian Bartilet')
            playwright.expect(dialog.get_by_text('Loading soul…')).to_be_visible()
            loading_height = dialog.bounding_box()['height']
            assert dialog.locator('.soul-status').evaluate("n=>getComputedStyle(n,'::before').animationName") == 'soul-spin'
            page.wait_for_timeout(100)
            assert pending
            serve(pending.pop())
            playwright.expect(dialog.get_by_text('Identity matching helpers', exact=True)).to_be_visible()
            assert abs(dialog.bounding_box()['height'] - loading_height) < 8
            assert dialog.locator('form > details > summary').all_text_contents() == ['Identity details', 'Connections', 'Identity matching helpers']
            pill = dialog.locator('header .connection-type-pill')
            assert pill.evaluate("n=>getComputedStyle(n).color") == 'rgb(255, 189, 145)'
            help_button = dialog.get_by_label('About Soul', exact=True)
            help_button.click()
            help_text = dialog.locator('.soul-help > p')
            playwright.expect(help_text).to_be_visible()
            box = help_text.bounding_box()
            assert box['x'] >= 0 and box['x'] + box['width'] <= width
            page.keyboard.press('Escape')
            playwright.expect(help_text).not_to_be_visible()
            playwright.expect(dialog).to_be_visible()
            dialog.get_by_text('Identity details', exact=True).click()
            identity = dialog.locator('form > details').first
            playwright.expect(identity.get_by_label('Display name', exact=True)).to_be_visible()
            phones = identity.get_by_label('Phone numbers', exact=True)
            references = identity.get_by_label('References', exact=True)
            assert phones.get_attribute('rows') == references.get_attribute('rows') == '1'
            if width > 540:
                assert abs(phones.bounding_box()['y'] - references.bounding_box()['y']) < 2
            dialog.get_by_text('Connections', exact=True).click()
            playwright.expect(dialog.locator('.connection-result-card').first).to_be_visible()
            footer = dialog.locator('footer')
            footer.scroll_into_view_if_needed()
            last_section = dialog.locator('form > details').last
            assert footer.bounding_box()['y'] >= last_section.bounding_box()['y'] + last_section.bounding_box()['height']
            assert dialog.evaluate('n=>n.scrollWidth<=n.clientWidth')
            page.screenshot(path=f'results/soul-layout-{width}.png')
        finally:
            browser.close()
