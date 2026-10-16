import json
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect

from test_action_editing import editor_page
from test_hfl_ideas import ideas
from test_corpus_workspaces import workspace_corpus
from modules.hfl_corpus.corpus import CorpusEntry


@pytest.fixture
def feed_corpus(workspace_corpus, monkeypatch):
    from modules.hfl_corpus.corpus import corpus_index
    rows = [CorpusEntry(str(i), (datetime(2026, 1, 1) + timedelta(hours=i)).isoformat(),
        f'Entry {i}', 'Reading', ('work',), 'notes',
        f'Source: notes\nMoment: Entry {i}\nWhat happened: Read entry {i}\nTags: #work') for i in range(105)]
    rows += [replace(rows[0], anchor='secret', moment='PRIVATE', secret=True),
             replace(rows[0], anchor='undated', header='No recorded date', moment='Undated'),
             replace(rows[0], anchor='other', tags=('other',), source='git')]
    documents = [replace(workspace_corpus, entries=tuple(rows), entry_count=len(rows))]
    monkeypatch.setattr(corpus_index, 'documents', lambda *args, **kwargs: tuple(documents))
    return documents


def test_feed_cursor_filters_secrets_and_new_insertions(authenticated_client, feed_corpus):
    client = authenticated_client
    params = {'q':'#work', 'source':'notes'}
    response = client.get('/hfl-corpus/curated-feed', params=params)
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    first = response.json()
    assert first['total'] == 106 and len(first['entries']) == 50
    assert first['entries'][0]['title'] == 'Entry 104'
    assert 'PRIVATE' not in response.text
    feed_corpus[0] = replace(feed_corpus[0], entries=(*feed_corpus[0].entries,
        replace(feed_corpus[0].entries[0], anchor='new', header='2026-12-01', moment='New')))
    second = client.get('/hfl-corpus/curated-feed', params={**params,'cursor':first['next_cursor']}).json()
    third = client.get('/hfl-corpus/curated-feed', params={**params,'cursor':second['next_cursor']}).json()
    all_entries = first['entries'] + second['entries'] + third['entries']
    assert len({row['id'] for row in all_entries}) == len(all_entries) == 106
    assert third['next_cursor'] is None and third['entries'][-1]['title'] == 'Undated'
    assert client.get('/hfl-corpus/curated-feed', params={**params,'order':'asc','cursor':first['next_cursor']}).status_code == 422
    assert client.get('/hfl-corpus/curated-feed', params={**params,'cursor':'invalid'}).status_code == 422
    oldest = client.get('/hfl-corpus/curated-feed', params={**params,'order':'asc'}).json()
    assert oldest['entries'][0]['title'] == 'Entry 0'
    assert client.get('/hfl-corpus/curated-feed', params={**params,'show_secrets':'true'}).json()['total'] == 107  # still locked


def test_feed_auth_validation_and_scope(authenticated_client, feed_corpus):
    from main import app
    with TestClient(app) as anonymous:
        assert anonymous.get('/hfl-corpus/curated-feed?q=work').status_code == 401
        assert anonymous.get('/api/hfl/curated-feed?q=work').status_code == 401
    assert authenticated_client.get('/hfl-corpus/curated-feed?sort=asc').status_code == 422
    assert authenticated_client.get('/hfl-corpus/curated-feed?q=work&date_from=bad').status_code == 422
    scope = json.dumps({'any':[{'source':'notes','q':'#work'}]})
    result = authenticated_client.get('/hfl-corpus/curated-feed', params={'scope':scope,'date_field':'entry','date_from':'2026-01-02','date_to':'2026-01-02'}).json()
    assert result['total'] == 24
    assert all('/hfl-corpus/document/today.md#' in entry['href'] for entry in result['entries'])
    assert authenticated_client.get('/hfl-corpus/curated-feed?q=absent').json()['entries'] == []


def test_saved_feed_preserves_combined_rules(authenticated_client, feed_corpus):
    from modules.hfl_corpus.workspace_views import WorkspaceWrite, save
    from modules.hfl_corpus.view_scope import predicate, resolved
    scope = json.dumps({'any':[{'source':'git'}, {'q':'#work'}], 'all':{'date_field':'entry','date_from':'2026-01-03'}})
    saved = save(WorkspaceWrite(name='Reading', state={'entry_scope':scope}))
    check = predicate(resolved(saved['state']))
    matches = [entry for entry in feed_corpus[0].entries if check(feed_corpus[0], entry)]
    assert len(matches) == 57
    response = authenticated_client.get('/hfl-corpus', params={**saved['state'],'workspace':saved['id']})
    assert response.status_code == 200 and 'name="scope"' in response.text
    from urllib.parse import parse_qs, urlparse
    normalized = parse_qs(urlparse(str(response.url)).query)
    result = authenticated_client.get('/hfl-corpus/curated-feed', params={'scope':normalized['scope'][0], 'date_from':'2026-01-01', 'date_field':'entry'}).json()
    assert result['total'] == 57  # Broader overrides cannot discard saved constraints.


def test_feed_remote_contract_does_not_trust_secret_flags(authenticated_client, feed_corpus, monkeypatch):
    from modules.hfl_corpus import router as routes
    from modules.hfl_corpus.curated_feed import feed_page
    from types import SimpleNamespace
    captured = {}
    def remote(*, params):
        captured.update(params)
        return feed_page(params, include_secrets=params['include_secrets'] == 'true', secret_tags=('secrets',))
    monkeypatch.setattr(routes, '_uses_remote_corpus', lambda: True)
    monkeypatch.setattr(routes.RemoteCorpusClient, 'from_settings', lambda: SimpleNamespace(curated_feed=remote))
    result = authenticated_client.get('/hfl-corpus/curated-feed?q=%23work&show_secrets=true&include_secrets=true&secret_tags=other')
    assert result.status_code == 200 and 'PRIVATE' not in result.text
    assert captured['include_secrets'] == 'false' and captured['secret_tags'] == 'secrets'
    canonical = authenticated_client.get('/api/hfl/curated-feed?q=%23work', headers={'Authorization':'Bearer frontend-test-hfl-api-token'})
    assert canonical.status_code == 200 and canonical.json()['total'] == 106


def test_saved_feed_rejects_malformed_or_deep_scope():
    from modules.hfl_corpus.workspace_views import WorkspaceState
    for raw in ('[]', '{"any":[null]}', '{"any":null}'):
        with pytest.raises(ValueError):
            WorkspaceState(entry_scope=raw)
    scope = ''
    for _ in range(7):
        scope = json.dumps({'any':[{'entry_scope':scope}]})
    with pytest.raises(ValueError):
        WorkspaceState(entry_scope=scope)


def test_combined_feed_space_handoff_preserves_rolling_rules(editor_page, feed_corpus):
    from modules.hfl_corpus import workspace_views
    from urllib.parse import urlencode
    page, client = editor_page
    first = workspace_views.save(workspace_views.WorkspaceWrite(name='Recent notes', state={'source':'notes','rolling':7}))
    second = workspace_views.save(workspace_views.WorkspaceWrite(name='Work', state={'q':'#work'}))
    data = workspace_views.listing()
    url = workspace_views.selection_url(data, [first['id'], second['id']])
    page.goto('https://editing.test' + url)
    page.locator('[data-curated-feed-open]').click()
    expect(page.locator('[data-feed-status]')).not_to_have_text('Loading entries…')
    page.locator('[data-feed-save]').click()
    page.wait_for_url('**/spaces?draft=1')
    page.locator('#space-destination').select_option('new')
    page.locator('#space-apply-draft').click()
    expect(page.locator('[data-feed-rules]')).to_be_visible()
    page.locator('#workspace-name').fill('Combined reading')
    page.get_by_role('button', name='Save Space', exact=True).click()
    expect(page.locator('#space-editor-title')).to_have_text('Edit Space')
    saved = next(view for view in client.get('/hfl-corpus/workspace-views').json()['views'] if view['name'] == 'Combined reading')
    rules = json.loads(saved['state']['entry_scope'])
    assert any(clause['rolling'] == 7 for clause in rules['any'])
    page.goto('https://editing.test/hfl-corpus?' + urlencode({**saved['state'],'workspace':saved['id']}))
    page.locator('[data-curated-feed-open]').click()
    expect(page.locator('.corpus-feed-card')).to_have_count(50)


@pytest.mark.parametrize('width', [390, 1440])
def test_feed_browser_keyboard_paging_retry_and_space(editor_page, feed_corpus, width, tmp_path):
    page, client = editor_page
    page.set_viewport_size({'width':width,'height':900})
    page.goto('https://editing.test/hfl-corpus?reset=1')
    expect(page.locator('[data-curated-feed-open]')).to_be_disabled()
    page.keyboard.press('v')
    expect(page.locator('[data-curated-feed]')).not_to_be_visible()
    page.goto('https://editing.test/hfl-corpus?q=%23work&source=notes')
    page.locator('#q').focus(); page.keyboard.press('v')
    expect(page.locator('[data-curated-feed]')).not_to_be_visible()
    page.locator('#q').fill('#work'); page.locator('[data-curated-feed-open]').focus(); page.keyboard.press('v')
    dialog = page.locator('[data-curated-feed]')
    expect(dialog).to_be_visible()
    expect(dialog.locator('.corpus-feed-card')).to_have_count(50)
    expect(dialog.locator('.corpus-feed-card h3').first).to_have_text('Entry 104')
    assert dialog.bounding_box()['width'] <= width
    page.screenshot(path=str(tmp_path / f'curated-feed-{width}.png'))
    scroller = dialog.locator('[data-feed-scroll]')
    scroller.evaluate('(el) => el.scrollTop = el.scrollHeight')
    expect(dialog.locator('.corpus-feed-card')).to_have_count(100)
    dialog.locator('[data-feed-order]').click()
    expect(dialog.locator('.corpus-feed-card h3').first).to_have_text('Entry 0')
    page.keyboard.press('Escape')
    expect(dialog).not_to_be_visible()
    expect(page.locator('[data-curated-feed-open]')).to_be_focused()
    page.route('**/hfl-corpus/curated-feed?**', lambda route: route.fulfill(status=503, json={'detail':'Retry test'}))
    page.keyboard.press('v')
    expect(dialog.locator('[data-feed-more]')).to_have_text('Retry')
    page.unroute('**/hfl-corpus/curated-feed?**')
    dialog.locator('[data-feed-more]').click()
    expect(dialog.locator('.corpus-feed-card')).to_have_count(50)
    dialog.locator('[data-feed-save]').click()
    page.wait_for_url('**/spaces?draft=1')
    page.locator('#space-destination').select_option('new')
    page.locator('#space-apply-draft').click()
    expect(page.locator('[data-edit-filter=q]')).to_have_value('#work')
    expect(page.locator('[data-edit-filter=source]')).to_have_value('notes')
    page.locator('#workspace-name').fill('Timeline reading')
    page.get_by_role('button', name='Save Space', exact=True).click()
    expect(page.locator('#space-editor-title')).to_have_text('Edit Space')
    saved = next(view for view in client.get('/hfl-corpus/workspace-views').json()['views'] if view['name'] == 'Timeline reading')
    assert saved['state']['q'] == '#work' and saved['state']['source'] == 'notes'


def test_view_feed_applies_pending_filters_before_opening(editor_page, feed_corpus):
    from urllib.parse import parse_qs, urlparse
    page, client = editor_page
    page.goto('https://editing.test/hfl-corpus?reset=1')
    button = page.locator('[data-curated-feed-open]')
    page.locator('#q').fill('#other')
    expect(button).to_be_enabled()
    button.click()
    dialog = page.locator('[data-curated-feed]')
    expect(dialog).to_be_visible()
    expect(dialog.locator('.corpus-feed-card')).to_have_count(1)
    assert parse_qs(urlparse(page.url).query)['q'] == ['#other']
    assert 'open_feed' not in parse_qs(urlparse(page.url).query)
    page.keyboard.press('v')
    expect(dialog).not_to_be_visible()
    page.locator('#q').fill('#work')
    page.get_by_role('button', name='Search', exact=True).click()
    expect(page.locator('[data-search-label]')).to_have_text('Search')
    expect(dialog).not_to_be_visible()
    page.locator('#q').fill('#other')
    button.click()
    expect(dialog).to_be_visible()
    expect(dialog.locator('.corpus-feed-card')).to_have_count(1)


def test_feed_excludes_summary_tag_index_but_keeps_real_tags_entry(authenticated_client, feed_corpus):
    from modules.hfl_corpus.corpus import parse_entries
    rows = parse_entries("""## Tags
Tags: #dogs #work #summary
## Undated note
Source: notes
Moment: Walking the dogs
Tags: #dogs
## Tags
Source: notes
Moment: Organizing dog tags
Tags: #dogs
""")
    feed_corpus[0] = replace(feed_corpus[0], entries=rows)
    result = authenticated_client.get('/hfl-corpus/curated-feed', params={'q': '#dogs'}).json()
    assert result['total'] == 2
    assert {entry['title'] for entry in result['entries']} == {'Walking the dogs', 'Organizing dog tags'}


def test_feed_resolves_only_visible_entry_attachments(authenticated_client, feed_corpus, tmp_path, monkeypatch):
    from modules.hfl_corpus import curated_feed as feed
    from modules.hfl_corpus.corpus import parse_entries
    import base64
    image = tmp_path / 'photo.png'
    image.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='))
    note = tmp_path / 'notes.txt'; note.write_text('Attachment text')
    monkeypatch.setattr(feed, 'resolve_corpus_root', lambda: tmp_path)
    monkeypatch.setattr(feed, 'allowed_reference_roots', lambda root: (tmp_path,))
    entries = parse_entries(f"""## 2026-01-01
Source: notes
Moment: Photo note
Tags: #dogs
References:
- {image.as_posix()}
- {note.as_posix()}
## 2026-01-02
Source: notes
Moment: Private photo
Tags: #other
References:
- {image.as_posix()}
""")
    feed_corpus[0] = replace(feed_corpus[0], path=tmp_path / 'entry.md', entries=entries)
    result = authenticated_client.get('/hfl-corpus/curated-feed', params={'q':'#dogs'}).json()
    assert result['total'] == 1
    row = result['entries'][0]
    assert [item['kind'] for item in row['attachments']] == ['image', 'download']
    assert row['attachments'][0]['media_url'].endswith('/media')
    assert row['attachments'][1]['href'].endswith('/download')
    assert str(tmp_path) not in row['html'] and 'References:' not in row['html']
    assert 'Source:' not in row['html'] and 'Tags:' not in row['html']


def test_remote_feed_rewrites_attachment_routes(monkeypatch):
    from modules.hfl_corpus.remote import RemoteCorpusClient
    from types import SimpleNamespace
    client = object.__new__(RemoteCorpusClient)
    monkeypatch.setattr(RemoteCorpusClient, '_get', lambda *a, **kw: SimpleNamespace(json=lambda: {
        'entries': [{'attachments': [{'token':'signed-token','href':'/hfl-corpus/references/signed-token/download',
                                     'media_url':'/hfl-corpus/references/signed-token/media','kind':'video'}]}]}))
    item = client.curated_feed(params={'q':'#dogs'})['entries'][0]['attachments'][0]
    assert item['href'] == '/hfl-corpus/remote-references/signed-token/download'
    assert item['media_url'] == '/hfl-corpus/remote-references/signed-token/media'
    assert 'token' not in item


def test_feed_audio_classification_is_opt_in_and_checks_content(tmp_path):
    from modules.hfl_shares.viewer import classify_preview
    import wave
    audio = tmp_path / 'clip.wav'
    with wave.open(str(audio), 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(8000); out.writeframes(b'\0\0' * 80)
    assert classify_preview(audio) is None
    assert classify_preview(audio, include_audio=True).kind == 'audio'
    audio.write_text('not audio')
    assert classify_preview(audio, include_audio=True) is None
