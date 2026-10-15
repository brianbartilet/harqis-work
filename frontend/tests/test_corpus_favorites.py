from dataclasses import replace
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup
import pytest

from modules.hfl_shares.security import make_csrf_token, hash_pin
from modules.profile.models import OwnerProfile
from modules.profile.store import get_profile_store
from test_action_editing import editor_page
from test_corpus_workspaces import workspace_corpus
from test_hfl_ideas import ideas


def form(**values):
    return {'csrf': make_csrf_token('frontend-test-user'), **values}


def test_favorites_save_preserves_profile_and_pin(authenticated_client):
    store = get_profile_store()
    original = OwnerProfile(nickname='Owner', secret_tags='#secrets, #private', secret_pin_hash=hash_pin('123456'))
    store.save(original)
    response = authenticated_client.post('/settings/corpus', data=form(favorite_tags=' Notes, #work, #notes, , #missing '))
    assert response.status_code == 200
    saved = store.get()
    assert saved.favorite_tags == '#Notes, #work, #missing'
    assert saved.secret_pin_hash == original.secret_pin_hash
    assert saved.secret_tags == original.secret_tags
    assert saved.nickname == 'Owner'
    authenticated_client.post('/profile', data=form(nickname='Updated'))
    assert store.get().favorite_tags == saved.favorite_tags
    assert store.get().secret_tags == saved.secret_tags
    assert store.get().secret_pin_hash == saved.secret_pin_hash
    page = BeautifulSoup(authenticated_client.get('/settings').text, 'html.parser')
    assert all(not section.has_attr('open') for section in page.select('details.settings-section'))
    assert not BeautifulSoup(authenticated_client.get('/profile').text, 'html.parser').select('#secret_tags')


def test_invalid_settings_are_atomic_and_pin_changes_require_current(authenticated_client):
    store = get_profile_store()
    original = OwnerProfile(favorite_tags='#old', secret_pin_hash=hash_pin('123456'))
    store.save(original)
    response = authenticated_client.post('/settings/corpus', data=form(favorite_tags='#new', new_secret_pin='654321', confirm_secret_pin='654321', current_secret_pin='000000'))
    assert response.status_code == 422
    assert 'Enter the current PIN.' in response.text
    assert 'value="#new"' in response.text
    assert store.get() == original
    assert authenticated_client.post('/settings/corpus', data={'favorite_tags':'#new'}).status_code == 403
    invalid = authenticated_client.post('/settings/corpus', data=form(favorite_tags='two words'))
    assert invalid.status_code == 422
    assert store.get() == original
    changed = authenticated_client.post('/settings/corpus', data=form(favorite_tags='', current_secret_pin='123456', new_secret_pin='654321', confirm_secret_pin='654321'))
    assert changed.status_code == 200
    assert store.get().favorite_tags == ''
    assert authenticated_client.post('/hfl-corpus/secrets/unlock', json={'pin':'654321'}).status_code == 200
    removed = authenticated_client.post('/settings/corpus', data=form(current_secret_pin='654321', remove_secret_pin='on'))
    assert removed.status_code == 200
    assert not store.get().secret_pin_hash
    assert not authenticated_client.cookies.get('hfl_secrets_unlocked')


def test_favorites_urls_preserve_other_filters_and_and_matching(authenticated_client, workspace_corpus):
    get_profile_store().save(OwnerProfile(favorite_tags='#work, #personal, #missing'))
    page = authenticated_client.get('/hfl-corpus?q=%23work+planning&source=git')
    soup = BeautifulSoup(page.text, 'html.parser')
    pills = soup.select('[data-favorite-tag]')
    assert [pill.text for pill in pills] == ['#work', '#personal', '#missing']
    assert pills[0]['aria-pressed'] == 'true'
    params = parse_qs(urlparse(pills[1]['href']).query)
    assert params['q'] == ['#work #personal planning']
    assert params['source'] == ['git']
    assert not workspace_corpus.matching_entries(('work', 'personal'))
    entry = replace(workspace_corpus.entries[0], tags=('notes-work', 'work'))
    entry2 = replace(entry, tags=('notes-1912026', 'personal'))
    doc = replace(workspace_corpus, entries=(entry, entry2))
    assert len(doc.matching_entries(('notes',))) == 2
    assert doc.matching_entries(('notes', 'work')) == (entry,)


@pytest.mark.parametrize('width', [1440, 390])
def test_favorites_browser_toggle_and_settings_link(editor_page, workspace_corpus, width, tmp_path):
    from playwright.sync_api import expect
    get_profile_store().save(OwnerProfile(favorite_tags='#work, #personal, #missing'))
    page, _ = editor_page
    page.set_viewport_size({'width': width, 'height': 1000})
    page.goto('https://editing.test/hfl-corpus')
    # Mobile search options are folded by the existing corpus filter panel.
    panel = page.locator('[data-favorite-tag]').first
    if not panel.is_visible():
        page.locator('label[for="mobile-date-filters"]').click()
    expect(panel).to_be_visible()
    expect(page.locator('[data-tag-cloud]')).not_to_have_attribute('open', '')
    page.locator('[data-favorite-tag][data-workspace-tag="work"]').click()
    expect(page.locator('#q')).to_have_value('#work')
    page.locator('[data-favorite-tag][data-workspace-tag="personal"]').click()
    expect(page.locator('#q')).to_have_value('#work #personal')
    page.locator('[data-favorite-tag][data-workspace-tag="work"]').click()
    expect(page.locator('#q')).to_have_value('#personal')
    page.locator('[data-tag-cloud] > summary').click()
    expect(page.locator('[data-tag-cloud] [data-workspace-tag]').first).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(tmp_path / f'corpus-favorites-{width}.png'))
    page.get_by_role('link', name='Edit quick tags', exact=True).click()
    expect(page.locator('#favorite_tags')).to_be_focused()
    expect(page.locator('#activity-corpus')).to_have_attribute('open', '')
    expect(page.locator('details.settings-section').first).not_to_have_attribute('open', '')
    page.locator('#favorite_tags').fill('notes, #notes, work')
    page.get_by_role('button', name='Save settings').click()
    expect(page.locator('#favorite_tags')).to_have_value('#notes, #work')
    expect(page.locator('#favorite_tags')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(tmp_path / f'corpus-settings-{width}.png'))


def test_combined_settings_save_validates_both_sections(authenticated_client):
    from modules.app_settings.store import read_settings
    page = BeautifulSoup(authenticated_client.get('/settings').text, 'html.parser')
    buttons = page.select('main button[type="submit"]')
    assert len(buttons) == 1 and buttons[0].text == 'Save settings'
    assert buttons[0].find_parent('details') is None
    assert len(page.select('main form')) == 1
    values = form(favorite_tags='notes, work', actions_polling_minutes='12')
    assert authenticated_client.post('/settings', data=values).status_code == 200
    assert read_settings()['actions_polling_minutes'] == 12
    assert get_profile_store().get().favorite_tags == '#notes, #work'
    invalid = {**values, 'actions_polling_minutes': '18', 'new_secret_pin': '12'}
    assert authenticated_client.post('/settings', data=invalid).status_code == 422
    assert read_settings()['actions_polling_minutes'] == 12
    invalid = {**values, 'actions_polling_minutes': '0', 'favorite_tags': 'changed'}
    assert authenticated_client.post('/settings', data=invalid).status_code == 422
    assert get_profile_store().get().favorite_tags == '#notes, #work'


@pytest.mark.parametrize('width', [1440, 390])
def test_expanded_tag_cloud_uses_full_width(editor_page, workspace_corpus, monkeypatch, width):
    from playwright.sync_api import expect
    from modules.hfl_corpus import router
    tags = tuple(f'project-topic-{i}' for i in range(100))
    document = replace(workspace_corpus, tags=tags, entries=tuple(
        replace(workspace_corpus.entries[0], anchor=f'entry-{i}', tags=(tag,))
        for i, tag in enumerate(tags)))
    monkeypatch.setattr(router.corpus_index, 'documents', lambda: (document,))
    get_profile_store().save(OwnerProfile(favorite_tags='#notes, #work'))
    page, _ = editor_page
    page.set_viewport_size({'width': width, 'height': 1000})
    page.goto('https://editing.test/hfl-corpus')
    if not page.locator('[data-tag-cloud] > summary').is_visible():
        page.locator('label[for="mobile-date-filters"]').click()
    page.locator('[data-tag-cloud] > summary').click()
    cloud = page.locator('[data-tag-cloud] > div')
    expect(cloud).to_be_visible()
    assert cloud.bounding_box()['width'] >= page.locator('.corpus-tags-row').bounding_box()['width'] - 2
    assert cloud.evaluate('(e) => e.scrollWidth <= e.clientWidth')
    pills = cloud.locator('[data-workspace-tag]')
    assert pills.count() == 100
    if width > 1000:
        assert pills.nth(1).bounding_box()['x'] > pills.first.bounding_box()['x']
    page.locator('[data-tag-cloud] > summary').click()
    expect(cloud).to_be_hidden()
    expect(page.locator('[data-favorite-tag]').first).to_be_visible()


@pytest.mark.parametrize('width', [1440, 390])
def test_settings_save_notice_auto_dismisses(editor_page, width):
    from playwright.sync_api import expect
    page, _ = editor_page
    page.set_viewport_size({'width': width, 'height': 1000})
    page.goto('https://editing.test/settings')
    page.get_by_role('button', name='Save settings', exact=True).click()
    notice = page.locator('#settings-save-notice')
    expect(notice).to_have_text('Settings saved.')
    assert notice.evaluate('(e) => getComputedStyle(e).position') == 'fixed'
    box = notice.bounding_box()
    assert 0 <= box['x'] and box['x'] + box['width'] <= width
    assert box['y'] < 150
    expect(notice).to_have_count(0, timeout=6000)
    page.reload()
    expect(notice).to_have_count(0)


@pytest.mark.parametrize('expanded', [[], ['agents'], ['activity-corpus'], ['agents', 'activity-corpus']])
def test_settings_save_preserves_expanded_sections(editor_page, expanded):
    from playwright.sync_api import expect
    page, _ = editor_page
    page.goto('https://editing.test/settings')
    for identity in expanded:
        page.locator('#' + identity + ' > summary').click()
    page.get_by_role('button', name='Save settings', exact=True).click()
    expect(page.locator('#settings-save-notice')).to_be_visible()
    assert page.locator('details.settings-section[open]').evaluate_all('(elements) => elements.map(e => e.id)') == expanded
    assert '#activity-corpus' not in page.url
