import json
from dataclasses import replace
from datetime import datetime

import pytest
from playwright.sync_api import expect

from test_action_editing import editor_page
from test_hfl_ideas import ideas
from test_corpus_workspaces import workspace_corpus
from modules.hfl_corpus.corpus import CorpusEntry
from modules.hfl_corpus.expressions import parse, project, generate, compile_expression, has_media
from modules.hfl_corpus.workspace_views import WorkspaceState
from modules.hfl_corpus.view_scope import predicate
from modules.hfl_shares.security import make_csrf_token


@pytest.fixture
def advanced_corpus(workspace_corpus, monkeypatch):
    from modules.hfl_corpus.corpus import corpus_index
    rows = (
        CorpusEntry('photo', '2026-01-01', 'Photo', 'Holiday', ('hfl',), 'instagram', 'Holiday\nReferences:\n - https://example.test/photo.jpg'),
        CorpusEntry('video', '2026-01-02', 'Video', 'Holiday', ('hfl-random',), 'notes', 'Holiday\nReferences:\n - /media/video.mp4'),
        CorpusEntry('audio', '2026-01-03', 'Audio', 'Work', ('work',), 'notes', 'Work\nReferences:\n - /media/audio.mp3'),
    )
    doc = replace(workspace_corpus, entries=rows, entry_count=3, created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 3))
    monkeypatch.setattr(corpus_index, 'documents', lambda *a, **k: (doc,))
    return doc


def test_nested_boolean_semantics_and_exact_exclusion(advanced_corpus):
    doc = advanced_corpus
    check = compile_expression('(source = "instagram" AND hasMedia = true) OR (tags = "work" AND NOT text ~ "Holiday")')
    assert [entry.anchor for entry in doc.entries if check(doc, entry)] == ['photo', 'audio']
    state = WorkspaceState(has_media=True, exclude_tags=' #HFL, hfl, ')
    assert state.exclude_tags == 'hfl'
    check = predicate(state.model_dump())
    assert [entry.anchor for entry in doc.entries if check(doc, entry)] == ['video']
    check = predicate(WorkspaceState(exclude_tags='#hfl-random').model_dump())
    assert [entry.anchor for entry in doc.entries if check(doc, entry)] == ['photo', 'audio']
    assert not has_media(doc.entries[2])
    assert has_media(replace(doc.entries[2], text='![Photo](https://example.test/test.PNG?x=1)'))


def test_expression_round_trip_preserves_branches(advanced_corpus):
    state = WorkspaceState(q='#hfl Holiday', source='notes,instagram', has_media=True, exclude_tags='work',
                           rolling=7, expression='source = "notes" OR tags = "hfl"')
    restored = WorkspaceState.model_validate(project(generate(state.model_dump())))
    assert restored.model_dump(exclude={'expression'}) == state.model_dump(exclude={'expression'})
    assert parse(restored.expression) == parse(state.expression)
    doc = advanced_corpus
    dates = compile_expression('entryDate >= "2026-01-02" AND created = "2026-01-01"')
    assert [entry.anchor for entry in doc.entries if dates(doc, entry)] == ['video', 'audio']


def test_projection_keeps_literal_text_and_empty_source_semantics(advanced_corpus):
    for expression in ('text IN ("Holiday", "Work")', 'text ~ "two  spaces"', 'source = ""', 'text ~ "#literal"'):
        state = WorkspaceState.model_validate(project(expression))
        assert state.expression
        original, projected = compile_expression(expression), predicate(state.model_dump())
        assert [original(advanced_corpus, entry) for entry in advanced_corpus.entries] == [projected(advanced_corpus, entry) for entry in advanced_corpus.entries]
    from modules.hfl_corpus.view_scope import filter_scope, ViewScope
    assert not filter_scope((advanced_corpus,), ViewScope(all=WorkspaceState(source='missing')))


@pytest.mark.parametrize('expression', ['source =', 'unknown = "x"', 'hasMedia = "true"', 'tags > "hfl"',
    'text ~ "x" trailing', 'source IN ()', 'entryDate = "bad"', '(tags = "x"',
    'tags = "work" OR rolling = 7', 'NOT sort = "desc"', '(' * 26 + 'tags = "x"' + ')' * 26])
def test_invalid_expressions_rejected(expression):
    with pytest.raises(ValueError):
        WorkspaceState.model_validate(project(expression))


def test_api_search_feed_space_and_recipe_preserve_filters(authenticated_client, advanced_corpus):
    client = authenticated_client
    response = client.post('/hfl-corpus/expression', json={'expression':'hasMedia = true AND tags NOT IN ("hfl")'})
    assert response.status_code == 200
    state = response.json()['state']
    result = client.get('/hfl-corpus/curated-feed', params=state)
    assert result.status_code == 200
    assert [entry['title'] for entry in result.json()['entries']] == ['Video']
    canonical = client.get('/api/hfl/documents', params={**state, 'compact':'true'}, headers={'Authorization':'Bearer frontend-test-hfl-api-token'})
    assert canonical.status_code == 200 and canonical.json()['total_entries'] == 1
    page = client.get('/hfl-corpus', params=state)
    assert page.status_code == 200 and 'data-advanced-filters' in page.text
    headers = {'X-CSRF-Token':make_csrf_token('frontend-test-user')}
    saved = client.post('/hfl-corpus/workspace-views', json={'name':'Advanced', 'state':state}, headers=headers)
    assert saved.status_code == 200 and saved.json()['state']['has_media']
    recipe = client.post('/sharing/from-corpus', data={'csrf':headers['X-CSRF-Token'], 'state':json.dumps(state)})
    assert recipe.status_code == 200
    from bs4 import BeautifulSoup
    scope = json.loads(BeautifulSoup(recipe.text, 'html.parser').find('input', {'name':'corpus_scope'})['value'])
    assert scope['all']['has_media'] and scope['all']['exclude_tags'] == 'hfl'
    assert client.post('/hfl-corpus/expression', json={'expression':'source ='}).status_code == 422


@pytest.mark.parametrize('width', [1440, 390])
def test_expression_browser_roundtrip_validation_and_apply(editor_page, advanced_corpus, width, tmp_path):
    page, client = editor_page
    page.set_viewport_size({'width':width, 'height':900})
    page.goto('https://editing.test/hfl-corpus?reset=1')
    panel = page.locator('[data-advanced-filters]')
    page.locator('[data-advanced-filter-trigger]').click()
    expect(panel.locator('[data-expression-apply]')).to_be_disabled()
    expect(panel.get_by_role('switch', name='Query mode', exact=True)).not_to_be_checked()
    page.get_by_role('button', name='Query mode help', exact=True).click()
    help_dialog = page.get_by_role('dialog', name='Query mode', exact=True)
    expect(help_dialog).to_be_visible()
    expect(help_dialog).to_contain_text('ORDER BY source ASC, entryDate DESC')
    assert help_dialog.bounding_box()['width'] <= width
    page.screenshot(path=str(tmp_path / f'query-help-{width}.png'))
    page.keyboard.press('Escape')
    expect(help_dialog).not_to_be_visible()
    expect(page.get_by_role('button', name='Query mode help', exact=True)).to_be_focused()
    expect(panel.locator('[data-expression-apply]')).to_be_disabled()
    panel.locator('[data-expression-toggle]').check()
    editor = panel.locator('[data-expression-editor]')
    expect(editor).to_be_enabled()
    expect(panel.locator('[data-expression-apply]')).to_be_enabled()
    editor.fill('')
    page.screenshot(path=str(tmp_path / f'suggestions-{width}.png'))
    editor.fill('hasMedia = true AND (tags = "hfl" OR tags = "hfl-random")')
    expect(page.locator('[data-media-toggle]')).to_be_checked()
    editor.fill('source =')
    expect(editor).to_have_attribute('aria-invalid', 'true')
    expect(page.locator('[data-media-toggle]')).to_be_checked()
    expect(panel.locator('[data-expression-apply]')).to_be_disabled()
    panel.locator('[data-expression-toggle]').uncheck()
    expect(panel.locator('[data-expression-apply]')).to_be_disabled()
    page.locator('[data-exclude-tags-menu] > summary').click()
    expect(page.locator('[data-exclude-tags-input]')).to_be_focused()
    popup = page.locator('[data-exclude-tags-menu] .corpus-quick-tags-editor').bounding_box()
    assert popup['x'] >= 0 and popup['x'] + popup['width'] <= width
    page.screenshot(path=str(tmp_path / f'exclude-menu-{width}.png'))
    page.locator('[data-exclude-tags-input]').fill('#hfl')
    page.locator('[data-exclude-tags-save]').click()
    expect(page.locator('[name=exclude_tags]')).to_have_value('#hfl')
    expect(page.locator('[data-exclude-tags-menu]')).not_to_have_attribute('open', '')
    expect(panel).to_have_attribute('open', '')
    expect(panel.locator('[data-expression-apply]')).to_be_disabled()
    panel.locator('[data-expression-toggle]').check()
    expect(panel.locator('[data-expression-apply]')).to_be_enabled()
    page.screenshot(path=str(tmp_path / f'advanced-{width}.png'))
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    feed_box = page.locator('[data-curated-feed-open]').bounding_box()
    panel_box = panel.locator('.corpus-advanced-panel').bounding_box()
    assert feed_box['y'] + feed_box['height'] <= panel_box['y']
    panel.locator('[data-expression-apply]').click()
    expect(page.locator('[name=exclude_tags]')).to_have_value('hfl')
    expect(page.locator('[name=expression]')).not_to_have_value('')
    expect(panel).to_have_attribute('open', '')
    expect(panel.locator('[data-expression-toggle]')).to_be_checked()
    expect(editor).to_be_enabled()
    expect(panel.locator('[data-expression-apply]')).to_be_enabled()
    editor.fill('tags = "hfl-random"')
    expect(panel.locator('[data-expression-apply]')).to_be_enabled()
    panel.locator('[data-expression-apply]').click()
    expect(page.locator('[name=expression]')).to_have_value('(tags = "hfl-random")')
    expect(panel).to_have_attribute('open', '')
    expect(panel.locator('[data-expression-toggle]')).to_be_checked()
    expect(editor).to_be_enabled()
    page.screenshot(path=str(tmp_path / f'query-applied-{width}.png'))
    page.locator('[data-curated-feed-open]').click()
    expect(page.locator('[data-feed-summary]')).to_contain_text('1 of 1')


def test_space_expression_save_reopen_and_keyboard_suggestions(editor_page, advanced_corpus):
    page, client = editor_page
    page.goto('https://editing.test/spaces')
    page.locator('#space-new').click()
    page.locator('#workspace-name').fill('Media branches')
    panel = page.locator('[data-advanced-filters]')
    panel.locator('summary').click()
    panel.locator('[data-expression-toggle]').check()
    expect(panel.locator('[data-expression-apply]')).to_be_enabled()
    editor = panel.locator('[data-expression-editor]')
    editor.fill('hasM')
    editor.press('ArrowDown')
    editor.press('Enter')
    expect(editor).to_have_value('hasMedia')
    editor.fill('source IN ("notes") AND (tags = "hfl-random" OR hasMedia = false)')
    expect(page.locator('[data-edit-filter=source]')).to_have_value('notes')
    expect(panel.locator('[data-expression-apply]')).to_be_enabled()
    page.get_by_role('button', name='Save Space', exact=True).click()
    expect(page.locator('#space-status')).to_contain_text('Space saved')
    saved = next(view for view in client.get('/hfl-corpus/workspace-views').json()['views'] if view['name'] == 'Media branches')
    assert saved['state']['source'] == 'notes' and 'OR' in saved['state']['expression']
    page.reload()
    page.get_by_role('button', name='Media branches', exact=False).first.click()
    expect(page.locator('[data-edit-filter=expression]')).to_have_value(saved['state']['expression'])


@pytest.mark.parametrize('query_mode', [False, True])
def test_tag_search_preserves_advanced_and_cloud(editor_page, advanced_corpus, query_mode):
    page, _ = editor_page
    page.goto('https://editing.test/hfl-corpus?reset=1')
    advanced = page.locator('[data-advanced-filters]')
    tags = page.locator('[data-tag-cloud]')
    page.locator('[data-advanced-filter-trigger]').click()
    tags.locator('summary').click()
    if query_mode:
        advanced.locator('[data-expression-toggle]').check()
        expect(advanced.locator('[data-expression-apply]')).to_be_enabled()
    from urllib.parse import parse_qs, urlparse
    tag = tags.locator('[data-workspace-tag]').first
    selected = '#' + tag.get_attribute('data-workspace-tag')
    tag.click()
    page.wait_for_url(lambda url: parse_qs(urlparse(url).query).get('q') == [selected])
    expect(advanced).to_have_attribute('open', '')
    expect(tags).to_have_attribute('open', '')
    expect(advanced.locator('[data-expression-toggle]')).to_be_checked(checked=query_mode)


@pytest.mark.parametrize('with_space,width', [(False, 390), (True, 1440)])
def test_expression_reset_restores_scope_and_keeps_editor(editor_page, advanced_corpus, with_space, width):
    page, client = editor_page
    page.set_viewport_size({'width': width, 'height': 900})
    url = '/hfl-corpus?reset=1&q=extra'
    if with_space:
        headers = {'X-CSRF-Token': make_csrf_token('frontend-test-user')}
        view = client.post('/hfl-corpus/workspace-views', json={
            'name': 'Work', 'state': {'q': '#work'}}, headers=headers).json()
        client.post('/hfl-corpus/workspace-views/' + view['id'] + '/select', headers=headers)
        url = '/hfl-corpus?views=' + view['id'] + '&q=extra'
    page.goto('https://editing.test' + url)
    advanced = page.locator('[data-advanced-filters]')
    page.locator('[data-advanced-filter-trigger]').click()
    page.locator('[data-tag-cloud] summary').click()
    expect(advanced.locator('[data-expression-reset]')).to_be_disabled()
    advanced.locator('[data-expression-toggle]').check()
    expect(advanced.locator('[data-expression-reset]')).to_be_enabled()
    advanced.locator('[data-expression-toggle]').uncheck()
    expect(advanced.locator('[data-expression-reset]')).to_be_disabled()
    advanced.locator('[data-expression-toggle]').check()
    editor = advanced.locator('[data-expression-editor]')
    editor.fill('invalid @')
    expect(editor).to_have_attribute('aria-invalid', 'true')
    reset = advanced.locator('[data-expression-reset]')
    apply_bounds = advanced.locator('[data-expression-apply]').bounding_box()
    reset_bounds = reset.bounding_box()
    assert reset_bounds['x'] >= apply_bounds['x'] + apply_bounds['width']
    assert reset_bounds['x'] + reset_bounds['width'] <= width
    reset.click()
    expect(page.locator('#q')).to_have_value('#work' if with_space else '')
    expect(advanced).to_have_attribute('open', '')
    expect(page.locator('[data-tag-cloud]')).to_have_attribute('open', '')
    expect(advanced.locator('[data-expression-toggle]')).to_be_checked()
    expect(advanced.locator('[data-expression-apply]')).to_be_enabled()
    expect(editor).not_to_have_value('invalid @')
    expect(advanced.locator('[data-expression-error]')).to_be_empty()
    if with_space:
        saved = client.get('/hfl-corpus/workspace-views').json()['views']
        assert next(item for item in saved if item['id'] == view['id'])['state']['q'] == '#work'


@pytest.mark.parametrize('advanced_open,tags_open', [(True, True), (True, False), (False, True), (False, False)])
def test_feed_preserves_filter_disclosures(editor_page, advanced_corpus, advanced_open, tags_open):
    page, _ = editor_page
    page.goto('https://editing.test/hfl-corpus?q=%23hfl')
    advanced = page.locator('[data-advanced-filters]')
    tags = page.locator('[data-tag-cloud]')
    if advanced_open:
        page.locator('[data-advanced-filter-trigger]').click()
    if tags_open:
        tags.locator('summary').click()
    page.locator('[data-curated-feed-open]').click()
    expect(page.locator('[data-feed-close]')).to_be_visible()
    assert advanced.evaluate('(el) => el.open') == advanced_open
    assert tags.evaluate('(el) => el.open') == tags_open
    page.locator('[data-feed-close]').click()
    expect(page.locator('[data-feed-close]')).not_to_be_visible()
    assert advanced.evaluate('(el) => el.open') == advanced_open
    assert tags.evaluate('(el) => el.open') == tags_open
