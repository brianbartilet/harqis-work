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
    panel.locator('summary').click()
    panel.locator('[data-expression-toggle]').check()
    editor = panel.locator('[data-expression-editor]')
    expect(editor).to_be_enabled()
    expect(panel.locator('[data-expression-apply]')).to_be_enabled()
    editor.fill('hasMedia = true AND (tags = "hfl" OR tags = "hfl-random")')
    expect(panel.locator('[data-media-toggle]')).to_be_checked()
    expect(panel.locator('[data-expression-summary]')).to_be_visible()
    editor.fill('source =')
    expect(editor).to_have_attribute('aria-invalid', 'true')
    expect(panel.locator('[data-media-toggle]')).to_be_checked()
    expect(panel.locator('[data-expression-apply]')).to_be_disabled()
    panel.locator('[data-expression-toggle]').uncheck()
    expect(panel.locator('[data-expression-apply]')).to_be_enabled()
    panel.locator('[name=exclude_tags]').fill('#hfl')
    expect(panel.locator('[data-expression-apply]')).to_be_enabled()
    page.screenshot(path=str(tmp_path / f'advanced-{width}.png'))
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    panel.locator('[data-expression-apply]').click()
    expect(page.locator('[name=exclude_tags]')).to_have_value('#hfl')
    expect(page.locator('[name=expression]')).not_to_have_value('')
    page.locator('[data-curated-feed-open]').click()
    expect(page.locator('[data-feed-summary]')).to_contain_text('1 of 1')
