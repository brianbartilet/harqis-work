"""Type property edits retain stable kinds and never start historical work."""
from pathlib import Path

import pytest

from workflows.hfl import entity_types
from workflows.hfl.entity_store import get_store
from test_entity_review_updates import review_data  # noqa: F401


@pytest.mark.parametrize('identity', ['people', 'vehicles'])
def test_edit_type_preserves_identity_and_does_not_backfill(review_data, authenticated_client, identity):
    if identity == 'vehicles':
        entity_types.create('Vehicles', '#aabbcc', 'Named vehicles')
    before = entity_types.revision()
    payload = dict(name='Updated name', color='#ABCDEF', description='Updated extraction guidance')
    response = authenticated_client.post(f'/api/hfl/entities/types/{identity}/update', json=payload)
    assert response.status_code == 200, response.text
    assert response.json() == dict(id=identity, **{**payload, 'color': '#abcdef'})
    assert entity_types.revision() != before
    assert next(t for t in entity_types.listing() if t['id'] == identity) == response.json()
    assert get_store().profiles()['a']['kind'] == 'people'
    assert get_store().state('entity-types-backfill') is None
    with get_store().connection() as db:
        assert db.execute('SELECT count(*) FROM entity_resolution_jobs').fetchone()[0] == 0
    duplicate = authenticated_client.post('/api/hfl/entities/types', json=payload)
    assert duplicate.status_code == 409


def test_type_edit_rejects_missing_duplicate_and_blank_values(review_data, authenticated_client):
    payload = dict(name='People', color='#aabbcc', description='Named people')
    before = entity_types.listing()
    assert authenticated_client.post('/api/hfl/entities/types/missing/update', json=payload).status_code == 404
    assert authenticated_client.post('/api/hfl/entities/types/tools/update', json=payload).status_code == 409
    for field in ('name', 'description'):
        assert authenticated_client.post('/api/hfl/entities/types/people/update', json={**payload, field: '   '}).status_code == 409
    assert entity_types.listing() == before


@pytest.mark.parametrize('width', [1100, 390])
def test_type_editor_browser_save_retry_and_reopen(review_data, authenticated_client, tmp_path, width):
    pw = pytest.importorskip('playwright.sync_api')
    with pw.sync_playwright() as engine:
        options = {'headless': True}
        if not Path(engine.chromium.executable_path).exists():
            options['channel'] = 'msedge'
        browser = engine.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            errors, writes = [], []
            page.on('pageerror', lambda e: errors.append(str(e)))
            def route_request(route):
                req = route.request
                if req.url.endswith('/types/people/update'):
                    writes.append(req.post_data_json)
                    if len(writes) == 1:
                        route.fulfill(status=503, content_type='application/json', body='{"detail":"Temporary failure"}')
                        return
                response = authenticated_client.request(req.method, req.url.replace('https://entities.test', ''),
                    content=req.post_data_buffer, headers={'content-type': req.headers.get('content-type', 'application/json')})
                route.fulfill(status=response.status_code, body=response.content,
                    headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-encoding', 'content-length'}})
            page.route('https://entities.test/**', route_request)
            page.goto('https://entities.test/hfl-corpus/entities')
            pw.expect(page.locator('#edit-entity-type')).to_be_enabled()
            page.locator('#entity-type-manager > summary').click()
            page.locator('#edit-entity-type').select_option('people')
            form = page.locator('#entity-type-form')
            pw.expect(form.locator('[name=name]')).to_have_value('People')
            form.locator('[name=name]').fill('Contacts')
            form.locator('[name=description]').fill('Named individuals and their roles.')
            form.get_by_role('button', name='Save type changes').click()
            pw.expect(page.locator('#type-feedback')).to_have_text('Temporary failure')
            pw.expect(form.locator('[name=name]')).to_have_value('Contacts')
            form.get_by_role('button', name='Save type changes').click()
            pw.expect(page.locator('#type-feedback')).to_contain_text('Type updated')
            pw.expect(page.locator('#edit-entity-type')).to_have_value('people')
            form.get_by_role('button', name='Cancel editing').click()
            pw.expect(form.locator('[name=name]')).to_have_value('')
            page.locator('#edit-entity-type').select_option('people')
            pw.expect(form.locator('[name=name]')).to_have_value('Contacts')
            pw.expect(form.locator('[name=description]')).to_have_value('Named individuals and their roles.')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert page.locator('script[src*="corpus-entities.js"]').get_attribute('src').find('?') != -1
            screenshot = tmp_path / f'type-editor-{width}.png'
            page.locator('#entity-type-manager').screenshot(path=str(screenshot))
            print('SCREENSHOT', screenshot)
            assert not errors
        finally:
            browser.close()
