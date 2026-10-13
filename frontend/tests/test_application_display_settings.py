import io
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from PIL import Image
from modules.applications import display_settings
from modules.applications.inventory import get_application, clear_application_cache
from modules.hfl_shares.security import make_csrf_token


@pytest.fixture(autouse=True)
def isolated_display_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(display_settings, 'get_settings', lambda: SimpleNamespace(profile_store_path=tmp_path/'display.sqlite3'))


def picture():
    output = io.BytesIO()
    Image.new('RGBA', (80, 40), (20, 120, 220, 100)).save(output, format='PNG')
    return output.getvalue()


def headers():
    return {'X-CSRF-Token': make_csrf_token('frontend-test-user')}


def test_shared_display_settings_persist_without_changing_inventory(authenticated_client):
    client = authenticated_client
    original = get_application('aaa').label
    response = client.post('/applications/aaa/settings', headers=headers(), data={'display_name':'My application'}, files={'icon':('icon.png', picture(), 'image/png')})
    assert response.status_code == 200, response.text
    icon_url = response.json()['icon_url']
    icon = client.get(icon_url)
    assert icon.headers['content-type'] == 'image/webp'
    with Image.open(io.BytesIO(icon.content)) as image:
        assert image.size == (80, 40)
        assert image.getpixel((0,0))[3] == 100
    clear_application_cache()
    assert get_application('aaa').label == original
    for url in ['/applications', '/applications/aaa', '/applications/aaa/docs/README.md']:
        assert 'My application' in client.get(url).text
    # A new connection to the persistent store sees the same settings.
    assert display_settings.decorate((get_application('aaa'),))[0].label == 'My application'
    response = client.post('/applications/aaa/settings', headers=headers(), data={'display_name':'Renamed'})
    assert response.json()['icon_url'] == icon_url
    assert client.post('/applications/aaa/settings/reset', headers=headers()).json()['display_name'] == original
    assert not display_settings.icon('aaa')
    assert 'img/connectors/application.svg' in client.get('/applications/aaa').text


def test_display_settings_validation_is_atomic_and_csrf_protected(authenticated_client):
    client = authenticated_client
    assert client.post('/applications/aaa/settings', data={'display_name':'No'}).status_code == 403
    assert client.post('/applications/aaa/settings/reset').status_code == 403
    display_settings.save('aaa', 'Saved', display_settings.normalize_image(picture()))
    saved_icon = display_settings.icon('aaa')
    for name in ['', ' ', 'x'*81, 'bad\x00name']:
        assert client.post('/applications/aaa/settings', headers=headers(), data={'display_name':name}).status_code == 422
    for raw in [b'not an image', b'<svg xmlns="http://www.w3.org/2000/svg"/>', b'x'*(2*1024*1024+1)]:
        assert client.post('/applications/aaa/settings', headers=headers(), data={'display_name':'Changed'}, files={'icon':('bad.png',raw,'image/png')}).status_code == 422
    assert display_settings.decorate((get_application('aaa'),))[0].label == 'Saved'
    assert display_settings.icon('aaa') == saved_icon
    assert client.post('/applications/not_real/settings', headers=headers(), data={'display_name':'Unknown'}).status_code == 404


@pytest.mark.parametrize('width', [390,1200])
def test_display_settings_in_browser(authenticated_client,tmp_path,width):
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as engine:
        options={'headless':True}
        if not Path(engine.chromium.executable_path).exists():options['channel']='msedge'
        browser=engine.chromium.launch(**options)
        page=browser.new_page(viewport={'width':width,'height':900})
        errors=[]
        page.on('pageerror', lambda error: errors.append(str(error)))
        def route(intercept):
            req=intercept.request;url=urlsplit(req.url)
            if url.hostname!='settings.test':intercept.abort();return
            response=authenticated_client.request(req.method,url.path+('?' + url.query if url.query else ''),content=req.post_data_buffer,
                headers={k:v for k,v in req.headers.items() if k.lower() in {'content-type','x-csrf-token'}})
            intercept.fulfill(status=response.status_code,body=response.content,headers={'content-type':response.headers.get('content-type','text/html')})
        page.route('**/*',route)
        try:
            page.goto('https://settings.test/applications/aaa')
            form=page.locator('[data-application-settings]')
            form.get_by_label('Display name',exact=True).fill('Friendly AAA')
            form.get_by_label('Icon image',exact=True).set_input_files({'name':'icon.png','mimeType':'image/png','buffer':picture()})
            form.get_by_role('button',name='Save',exact=True).click()
            playwright.expect(form.get_by_role('status')).to_have_text('Settings saved.')
            playwright.expect(page.get_by_role('heading',name='Friendly AAA',exact=True)).to_be_visible()
            page.reload()
            playwright.expect(form.get_by_label('Display name',exact=True)).to_have_value('Friendly AAA')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(tmp_path/f'display-settings-{width}.png'),full_page=True)
            page.goto('https://settings.test/applications#workflow-integrations')
            card=page.locator('[data-app-key="aaa"]')
            playwright.expect(card.get_by_role('heading',name='Friendly AAA',exact=True)).to_be_visible()
            assert '/applications/aaa/icon?v=' in card.locator('img').get_attribute('src')
            card.get_by_role('link').click()
            form.get_by_role('button',name='Reset to defaults').click()
            playwright.expect(form.get_by_role('status')).to_have_text('Defaults restored.')
            playwright.expect(page.get_by_role('heading',name='AAA',exact=True)).to_be_visible()
            assert not errors,errors
        finally:
            browser.close()
