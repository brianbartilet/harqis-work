from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from modules.hfl_corpus import workspace_views
from modules.hfl_corpus.corpus import CorpusDocument, CorpusEntry, search_documents, activity_counts
from modules.hfl_shares.security import make_csrf_token


@pytest.fixture
def workspace_corpus(monkeypatch):
    import modules.hfl_corpus.router as routes
    entries = tuple(CorpusEntry(str(i), f'{date.today()} 10:00', 'Planning', 'Project planning', tags, source, 'Project planning')
                    for i, (source, tags) in enumerate([('git', ('work',)), ('notes', ('work',)), ('browsing', ('personal',))]))
    document = CorpusDocument('today.md', None, 'today.md', 'Project planning', datetime.now(), datetime.now(), ('work', 'personal'), (), 'Planning', entries=entries, entry_count=3)
    monkeypatch.setattr(routes.corpus_index, 'documents', lambda: (document,))
    monkeypatch.setattr(routes.corpus_index, 'get', lambda path: document)
    with workspace_views.connection() as db:
        workspace_views.schema(db)
        db.execute('DELETE FROM corpus_workspace_views')
        db.execute('DELETE FROM corpus_workspace_last')
    yield document
    with workspace_views.connection() as db:
        db.execute('DELETE FROM corpus_workspace_views')
        db.execute('DELETE FROM corpus_workspace_last')


def test_multiple_sources_combine_with_tags_and_text(workspace_corpus):
    document = workspace_corpus
    assert len(document.matching_entries(('work',), 'planning', 'git,notes')) == 2
    assert not document.matching_entries(('personal',), '', 'git,notes')
    assert search_documents((document,), query='#work planning', source='git,notes') == [document]
    assert search_documents((document,), query='#personal', source='git,notes') == []
    assert sum(activity_counts((document,), year=date.today().year, query='#work', source='git,notes').values()) == 2


def test_workspace_api_restore_conflicts_and_security(authenticated_client, workspace_corpus):
    client = authenticated_client
    headers = {'X-CSRF-Token': make_csrf_token('frontend-test-user')}
    payload = {'name': 'Work', 'state': {'source': 'git,notes', 'q': '#work', 'rolling': 7, 'date_field': 'entry'}}
    assert client.post('/hfl-corpus/workspace-views', json=payload).status_code == 403
    response = client.post('/hfl-corpus/workspace-views', json=payload, headers=headers)
    assert response.status_code == 200
    view = response.json()
    url = '/hfl-corpus/workspace-views/' + view['id']
    restored = client.get('/hfl-corpus', follow_redirects=False)
    assert restored.status_code == 303
    params = parse_qs(urlparse(restored.headers['location']).query)
    assert params['source'] == ['git,notes'] and params['rolling'] == ['7']
    page = client.get(restored.headers['location'])
    assert page.status_code == 200
    assert f'value="{date.today().isoformat()}"' in page.text
    assert f'value="{(date.today()-timedelta(days=6)).isoformat()}"' in page.text
    assert '2 matching entries' in page.text
    assert client.get('/hfl-corpus?q=explicit', follow_redirects=False).status_code == 200
    assert client.get('/hfl-corpus?reset=1', follow_redirects=False).status_code == 200
    assert client.put(url, json={**payload, 'revision': 0}, headers=headers).status_code == 409
    assert client.post('/hfl-corpus/workspace-views', json={**payload, 'state': {'show_secrets': True}}, headers=headers).status_code == 422
    updated = client.put(url, json={**payload, 'name': 'Renamed', 'revision': view['revision']}, headers=headers)
    assert updated.status_code == 200
    assert client.delete(url+'?revision=1', headers=headers).status_code == 409
    assert client.delete(url+'?revision=2', headers=headers).status_code == 200
    assert client.get('/hfl-corpus/workspace-views').json() == {'views': [], 'last_used': None}
    assert client.get('/hfl-corpus', follow_redirects=False).status_code == 200


def test_multisource_local_and_canonical_api(authenticated_client, workspace_corpus):
    client = authenticated_client
    page = client.get('/hfl-corpus?source=git,notes&q=%23work&rolling=30&page_size=50')
    assert page.status_code == 200
    assert '2 matching entries' in page.text
    assert 'source=git%2Cnotes' in page.text and 'rolling=30' in page.text
    matches = client.get('/hfl-corpus/matches/today.md?source=git,notes&q=%23work')
    assert matches.status_code == 200
    # The canonical API uses the same index/view with bearer authorization.
    response = client.get('/api/hfl/documents?source=git,notes&q=%23work', headers={'Authorization': 'Bearer frontend-test-hfl-api-token'})
    assert response.status_code == 200
    assert response.json()['selected_source'] == 'git,notes'


def test_remote_multisource_search(authenticated_client, workspace_corpus, monkeypatch):
    from modules.hfl_corpus.remote import RemoteCorpusClient, RemoteCorpusError
    remote = RemoteCorpusClient('http://canonical.test/api/hfl', 'unused')
    def get(path, *, params):
        return authenticated_client.get('/api/hfl' + path, params=params,
            headers={'Authorization': 'Bearer frontend-test-hfl-api-token'})
    monkeypatch.setattr(remote, '_get', get)
    result = remote.index(params={'source': 'git,notes', 'q': '#work'})
    assert result['selected_source'] == 'git,notes'
    assert result['results'][0].matching_entry_count == 2
    payload = get('/documents', params={'source': 'git'}).json()
    payload['selected_source'] = ''
    import httpx
    monkeypatch.setattr(remote, '_get', lambda *a, **k: httpx.Response(200, json=payload))
    with pytest.raises(RemoteCorpusError, match='Update the corpus host'):
        remote.index(params={'source': 'git,notes'})


def test_workspace_mobile_and_desktop_browser(authenticated_client, workspace_corpus, tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as engine:
        options = {'headless': True}
        if not Path(engine.chromium.executable_path).exists():
            options['channel'] = 'msedge'
        browser = engine.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            def route_request(route):
                req = route.request
                response = authenticated_client.request(req.method, req.url.replace('http://workspace.test', ''), content=req.post_data,
                    headers={key: value for key, value in req.headers.items() if key in {'content-type', 'x-csrf-token'}}, follow_redirects=True)
                route.fulfill(status=response.status_code, body=response.content,
                    headers={key: value for key, value in response.headers.items() if key.lower() not in {'content-encoding', 'content-length'}})
            page.route('http://workspace.test/**', route_request)
            page.goto('http://workspace.test/hfl-corpus')
            page.locator('label[for="mobile-date-filters"]').click()
            page.locator('[data-workspace-sources] summary').click()
            page.locator('[data-source-option][value="git"]').check()
            page.locator('[data-source-option][value="notes"]').check()
            page.locator('#q').fill('#work')
            page.select_option('[name="rolling"]', '7')
            assert page.locator('[name="date_from"]').is_disabled()
            # Observe feedback synchronously before the navigation completes.
            page.evaluate("""() => document.getElementById('corpus-search-form').addEventListener('submit', () => {
                sessionStorage.setItem('search-feedback', document.querySelector('[data-search-label]').textContent);
            })""")
            page.locator('[data-corpus-search]').click()
            page.wait_for_load_state()
            assert page.evaluate("sessionStorage.getItem('search-feedback')") == 'Searching…'
            assert '2 matching entries' in page.locator('[data-corpus-results]').inner_text()
            page.locator('[data-workspace-menu] summary').click()
            page.locator('[data-workspace-action="new"]').click()
            page.locator('#workspace-name').fill('Work sources')
            page.locator('[data-workspace-confirm]').click()
            page.wait_for_function("document.querySelector('[data-workspace-status]').textContent==='Saved: Work sources'")
            view = authenticated_client.get('/hfl-corpus/workspace-views').json()['views'][0]
            assert view['state']['source'] == 'git,notes'
            assert view['state']['rolling'] == 7
            for width, height in [(390, 844), (320, 740), (1440, 1000)]:
                page.set_viewport_size({'width': width, 'height': height})
                page.evaluate("window.scrollTo(0,0); document.querySelector('[data-corpus-index]').scrollTop=0")
                page.locator('[data-workspace-menu]').evaluate('(el) => el.open = true')
                panel = page.locator('.workspace-menu-panel').bounding_box()
                assert panel['x'] >= 0 and panel['x'] + panel['width'] <= width
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(tmp_path / f'workspace-{width}.png'), full_page=True)
                page.locator('[data-workspace-menu]').evaluate('(el) => el.open = false')
                page.locator('[data-workspace-sources]').evaluate('(el) => el.open = true')
                source_panel = page.locator('.workspace-source-options').bounding_box()
                assert source_panel['x'] >= 0 and source_panel['x'] + source_panel['width'] <= width
                page.screenshot(path=str(tmp_path / f'workspace-filters-{width}.png'), full_page=True)
                page.locator('[data-workspace-sources]').evaluate('(el) => el.open = false')
            page.locator('[data-workspace-menu]').evaluate('(el) => el.open = false')
            page.locator('#q').fill('unsaved draft')
            page.goto('about:blank')
            page.goto('http://workspace.test/hfl-corpus')
            assert page.locator('#q').input_value() == '#work'
            assert page.locator('[name="rolling"]').input_value() == '7'
            page.locator('#q').fill('#work planning')
            page.locator('[data-workspace-menu] summary').click()
            page.locator('[data-workspace-action="save"]').click()
            page.wait_for_function("document.querySelector('[data-workspace-status]').textContent==='Saved: Work sources'")
            assert authenticated_client.get('/hfl-corpus/workspace-views').json()['views'][0]['state']['q'] == '#work planning'
            page.locator('#q').fill('#personal')
            page.locator('[data-workspace-action="new"]').click()
            page.locator('#workspace-name').fill('Personal')
            page.locator('[data-workspace-confirm]').click()
            page.wait_for_function("document.querySelector('[data-workspace-status]').textContent==='Saved: Personal'")
            page.select_option('[data-workspace-selection]', view['id'])
            page.wait_for_function("document.querySelector('#q').value==='#work planning'")
            page.locator('[data-workspace-menu] summary').click()
            page.locator('[data-workspace-action="edit"]').click()
            page.locator('#workspace-name').fill('Renamed workspace')
            page.locator('[data-workspace-confirm]').click()
            page.wait_for_function("document.querySelector('[data-workspace-status]').textContent==='Saved: Renamed workspace'")
            page.locator('[data-workspace-action="remove"]').click()
            page.locator('[data-workspace-confirm]').click()
            page.wait_for_url('**/hfl-corpus?reset=1')
            assert page.locator('#q').input_value() == ''
            remaining = authenticated_client.get('/hfl-corpus/workspace-views').json()
            assert [item['name'] for item in remaining['views']] == ['Personal']
            assert remaining['last_used'] is None
            assert not errors, errors
            print(f'Workspace screenshots: {tmp_path}')
        finally:
            browser.close()
