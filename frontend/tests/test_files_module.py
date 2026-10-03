import json
import os
import time
from uuid import uuid4

import pytest

from apps.file_index.store import Store
from apps.file_index.service import scan


@pytest.fixture
def files_env(tmp_path, monkeypatch):
    monkeypatch.setenv('FILES_STORE_PATH', str(tmp_path / 'files.sqlite3'))
    monkeypatch.setenv('FILES_ALLOWED_ROOTS', json.dumps([str(tmp_path)]))
    monkeypatch.setenv('FILES_HOST_ID', 'test-host')
    return tmp_path


def test_owner_routes_and_csrf(authenticated_client, files_env):
    client = authenticated_client
    page = client.get('/files')
    assert page.status_code == 200
    assert 'Your files, connected.' in page.text
    assert client.get('/files/api/indexing-status').status_code == 200
    payload = {'name': 'Docs', 'root': str(files_env), 'kind': 'local', 'host': 'test-host'}
    assert client.post('/files/api/sources', json=payload).status_code == 403
    assert client.post('/files/api/sources', json=payload, headers={'X-Harqis-Files': '1', 'Origin': 'https://attacker.test'}).status_code == 403
    response = client.post('/files/api/sources', json=payload, headers={'X-Harqis-Files': '1'})
    assert response.status_code == 200
    assert client.get('/files/api/sources').json()['items'][0]['name'] == 'Docs'
    client.cookies.clear()
    assert client.get('/files/api/catalog').status_code == 401
    assert client.get('/files/api/indexing-status').status_code == 401


def test_catalog_package_guest_boundary(authenticated_client, files_env):
    client = authenticated_client
    root = files_env / 'documents'
    root.mkdir()
    (root / 'brief.html').write_text('<script>alert(1)</script>')
    headers = {'X-Harqis-Files': '1'}
    source = client.post('/files/api/sources', headers=headers, json={
        'name': 'Docs', 'kind': 'local', 'root': str(root), 'host': 'test-host'}).json()
    scan(source['id'])
    file = client.get('/files/api/catalog').json()['items'][0]
    assert client.patch('/files/api/files/'+file['id'], headers=headers,
        json={'categories': ['3'], 'tags': ['<script>'], 'entities': ['entity:test']}).status_code == 200
    graph = client.get('/files/api/graph').json()
    assert len(graph['nodes']) == 3
    download = client.get('/files/api/files/'+file['id']+'/download')
    assert download.headers['content-disposition'].startswith('attachment;')
    package = client.post('/files/api/packages', headers=headers, json={'title': '<script>Secret</script>', 'expiry_days': 7}).json()
    rev = client.post('/files/api/packages/'+package['id']+'/revisions', headers=headers,
        json={'file_ids': [file['id']], 'request_id': str(uuid4())}).json()
    assert client.get('/file-share/'+rev['token']).status_code == 404

    rev.update(state='published', drive_url='https://drive.google.com/drive/folders/test', expires_at=time.time()+100,
               copies={file['id']: {'name': 'brief.html', 'size': 10, 'mime_type': 'text/html', 'url': 'https://drive.google.com/file/d/test/view'}})
    Store().put('revisions', rev)
    client.cookies.clear()
    guest = client.get('/file-share/'+rev['token'])
    assert guest.status_code == 200
    assert '&lt;script&gt;Secret&lt;/script&gt;' in guest.text
    assert str(root) not in guest.text
    assert 'entity:test' not in guest.text
    assert guest.headers['cache-control'] == 'no-store'
    assert guest.headers['referrer-policy'] == 'no-referrer'
    assert "script-src 'self' 'nonce-" in guest.headers['content-security-policy']
    rev['expires_at'] = time.time()-1
    Store().put('revisions', rev)
    assert client.get('/file-share/'+rev['token']).status_code == 404


def test_browser_catalog_to_package(authenticated_client, files_env, monkeypatch):
    """Exercise real JS/forms with in-process HTTP routing and temporary data."""
    from pathlib import Path
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright
    root = files_env / 'documents'
    root.mkdir()
    (root / 'Research brief.md').write_text('A brief for the project.')
    (root / 'Archive').mkdir()
    (root / 'Archive' / 'older.txt').write_text('Earlier notes.')
    monkeypatch.setenv('FILES_ALLOWED_ROOTS', json.dumps([str(root)]))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.environ.get('FILES_TEST_BROWSER_CHANNEL') or None)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def handle(route):
            request = route.request
            parsed = urlsplit(request.url)
            if parsed.hostname != 'testserver':
                route.abort()
                return
            response = authenticated_client.request(request.method, parsed.path + ('?' + parsed.query if parsed.query else ''),
                content=request.post_data_buffer, headers={k:v for k,v in request.headers.items() if k.lower() not in {'host', 'cookie'}})
            headers = {k:v for k,v in response.headers.items() if k.lower() not in {'content-encoding', 'content-length', 'transfer-encoding'}}
            route.fulfill(status=response.status_code, headers=headers, body=response.content)
        page.route('**/*', handle)
        page.goto('http://testserver/files')
        screenshot = Path('results/files-preview')
        screenshot.mkdir(parents=True, exist_ok=True)
        page.get_by_role('heading', name='Your catalog is ready for its first files').wait_for()
        assert not page.get_by_text('Advanced: register a file reference', exact=True).is_visible()
        page.screenshot(path=str(screenshot / 'empty.png'), full_page=True)
        page.get_by_role('button', name='Browse folders', exact=True).click()
        page.get_by_role('button', name='Open folder Archive', exact=True).click()
        page.get_by_label('older.txt', exact=True).wait_for()
        page.locator('#folder-breadcrumbs').get_by_role('button', name='documents', exact=True).click()
        page.get_by_label('Research brief.md', exact=True).check()
        page.screenshot(path=str(screenshot / 'picker.png'), full_page=True)
        page.get_by_role('button', name='Add selected files', exact=True).click()
        page.get_by_role('button', name='Research brief.md', exact=True).wait_for()
        page.get_by_role('button', name='Research brief.md', exact=True).click()
        page.locator('#metadata-form [name=tags]').fill('research, review')
        page.get_by_role('button', name='Save metadata', exact=True).click()
        page.get_by_label('Select Research brief.md', exact=True).check()
        page.get_by_role('button', name='Create package from selection', exact=True).click()
        page.locator('#package-form [name=title]').fill('Project review')
        page.get_by_role('button', name='Create draft revision', exact=True).click()
        page.get_by_role('heading', name='Revision 1 · draft').wait_for()
        page.screenshot(path=str(screenshot / 'packages.png'), full_page=True)
        page.get_by_role('button', name='Catalog', exact=True).click()
        page.get_by_role('button', name='Research brief.md', exact=True).wait_for()
        page.screenshot(path=str(screenshot / 'catalog.png'), full_page=True)
        page.get_by_role('button', name='Graph', exact=True).click()
        page.locator('#files-graph circle').wait_for()
        page.screenshot(path=str(screenshot / 'graph.png'), full_page=True)
        page.get_by_role('button', name='Catalog', exact=True).click()
        page.get_by_label('Search files', exact=True).fill('does-not-exist')
        page.get_by_role('button', name='Filter', exact=True).click()
        page.get_by_role('heading', name='No files match these filters').wait_for()
        page.get_by_role('button', name='Clear filters', exact=True).click()
        page.get_by_role('button', name='Research brief.md', exact=True).wait_for()
        page.get_by_role('button', name='Locations', exact=True).click()
        page.get_by_role('heading', name='Your locations').wait_for()
        page.screenshot(path=str(screenshot / 'locations.png'), full_page=True)
        page.get_by_role('button', name='Add remote location', exact=True).click()
        assert page.get_by_label('Google Drive folder link or ID', exact=True).is_visible()
        assert not page.get_by_label('SFTP connection profile', exact=True).is_visible()
        page.get_by_label('Storage', exact=True).select_option('sftp')
        assert page.get_by_label('SFTP connection profile', exact=True).is_visible()
        page.get_by_role('button', name='Catalog', exact=True).click()
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(screenshot / 'mobile.png'), full_page=True)
        assert page.locator('body').evaluate('(e)=>e.scrollWidth <= window.innerWidth')
        page.get_by_role('button', name='Browse folders', exact=True).click()
        page.locator('#folder-dialog').get_by_role('checkbox', name='Research brief.md', exact=True).wait_for()
        page.screenshot(path=str(screenshot / 'picker-mobile.png'), full_page=True)
        assert page.locator('#folder-dialog').evaluate('(e)=>e.scrollWidth <= e.clientWidth')
        assert not errors
        browser.close()


def test_picker_api_authorization_and_boundaries(authenticated_client, files_env):
    client = authenticated_client
    (files_env / 'real.txt').write_text('hello')
    source, = client.get('/files/api/sources').json()['items']
    assert source['configured_root'] is True
    url = '/files/api/sources/' + source['id']
    assert client.get(url + '/browse').status_code == 200
    assert client.get(url + '/browse', params={'path': '../'}).status_code == 403
    payload = {'paths': ['real.txt']}
    assert client.post(url + '/select', json=payload).status_code == 403
    result = client.post(url + '/select', json=payload, headers={'X-Harqis-Files': '1'})
    assert result.status_code == 200
    assert result.json()['items'][0]['name'] == 'real.txt'
    client.cookies.clear()
    assert client.get(url + '/browse').status_code == 401


def test_drive_folder_link_and_paused_scan_feedback(authenticated_client, files_env):
    client = authenticated_client
    headers = {'X-Harqis-Files': '1'}
    response = client.post('/files/api/sources', headers=headers, json={
        'name': 'Drive', 'kind': 'drive', 'root': 'https://drive.google.com/drive/u/0/folders/folder_123?usp=sharing'})
    assert response.status_code == 200
    assert response.json()['root'] == 'folder_123'
    source = response.json()
    Store().patch('sources', source['id'], {'enabled': False})
    response = client.post('/files/api/sources/' + source['id'] + '/scan', headers=headers)
    assert response.status_code == 409 and 'paused' in response.json()['detail']
