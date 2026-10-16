import json
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from playwright.sync_api import expect

from test_action_editing import editor_page
from test_hfl_ideas import ideas
from test_corpus_workspaces import workspace_corpus
from modules.hfl_corpus.corpus import CorpusEntry
from modules.hfl_corpus.expressions import generate, project
from modules.hfl_corpus.ordering import parse_order, sorted_pairs, sorted_documents
from modules.hfl_corpus.workspace_views import WorkspaceState
from modules.hfl_corpus.view_scope import ViewScope, filter_scope


@pytest.fixture
def ordered_corpus(workspace_corpus, monkeypatch):
    from modules.hfl_corpus.corpus import corpus_index
    rows = tuple(CorpusEntry(str(i), header, str(i), 'Sorting', ('work',), source,
                            f'Source: {source}\nMoment: {i}\nTags: #work')
                 for i, (source, header) in enumerate([
                     ('Zulu', '2026-01-01 12:00'), ('alpha', '2026-01-01 09:00'),
                     ('Alpha', '2026-01-02 10:00'), ('alpha', 'Unknown'), ('', '2026-01-03'),
                     ('alpha', '2026-01-01 09:00')]))
    docs = (replace(workspace_corpus, relative_path='one.md', entries=rows[:2], entry_count=2),
            replace(workspace_corpus, relative_path='two.md', entries=rows[2:], entry_count=4))
    monkeypatch.setattr(corpus_index, 'documents', lambda *a, **kw: docs)
    return docs


def test_order_by_parsing_generation_and_direction():
    state = WorkspaceState.model_validate(project('hasMedia = true ORDER BY source ASC, entryDate DESC'))
    assert state.order_by == 'source ASC, entryDate DESC' and state.sort == 'asc'
    assert generate(state.model_dump()).endswith('ORDER BY source ASC, entryDate DESC')
    assert 'sort =' not in generate(state.model_dump())
    assert WorkspaceState.model_validate(project(generate(state.model_dump()))) == state
    assert WorkspaceState.model_validate(project('order by source, updated desc')).order_by == 'source ASC, updated DESC'
    assert WorkspaceState(order_by='source ASC, entryDate DESC', sort='desc').order_by == 'source DESC, entryDate DESC'
    assert not project('text ~ "literal ORDER BY text"').get('order_by')
    assert project('sort = "asc" ORDER BY source ASC')['sort'] == 'asc'


@pytest.mark.parametrize('expression', [
    'ORDER BY', 'ORDER BY source UP', 'ORDER BY source ASC,', 'ORDER BY source, source',
    'ORDER BY tags', 'ORDER BY source AND hasMedia = true', 'ORDER BY source ORDER BY created',
    'hasMedia = true AND ORDER BY source', '(hasMedia = true ORDER BY source)',
    'sort = "desc" ORDER BY source ASC',
])
def test_invalid_order_by(expression):
    with pytest.raises(ValueError):
        WorkspaceState.model_validate(project(expression))


def test_multifield_order_missing_last_and_document_representative(ordered_corpus):
    pairs = [(doc, entry) for doc in ordered_corpus for entry in doc.entries]
    assert [row[2].anchor for row in sorted_pairs(pairs, 'source ASC, entryDate DESC')] == ['2', '1', '5', '3', '0', '4']
    assert [row[2].anchor for row in sorted_pairs(pairs, 'source DESC, entryDate ASC')] == ['0', '1', '5', '2', '3', '4']
    documents = sorted_documents(ordered_corpus, 'source ASC, entryDate DESC')
    assert [doc.relative_path for doc in documents] == ['two.md', 'one.md']
    assert [entry.anchor for entry in documents[0].entries] == ['2', '5', '3', '4']
    filtered = filter_scope(ordered_corpus, ViewScope(all=WorkspaceState(q='0', order_by='source ASC')))
    assert [entry.anchor for doc in filtered for entry in doc.entries] == ['0']
    empty = replace(ordered_corpus[0], relative_path='empty.md', entries=())
    assert filter_scope((*ordered_corpus, empty), ViewScope(all=WorkspaceState(order_by='entryDate DESC')))[-1].relative_path == 'empty.md'


def test_api_feed_and_recipe_order(authenticated_client, ordered_corpus):
    client = authenticated_client
    state = WorkspaceState.model_validate(project('ORDER BY source ASC, entryDate DESC')).model_dump()
    feed = client.get('/hfl-corpus/curated-feed', params=state)
    assert feed.status_code == 200
    assert [entry['title'] for entry in feed.json()['entries']] == ['2', '1', '5', '3', '0', '4']
    documents = client.get('/api/hfl/documents', params={**state, 'compact':'true'}, headers={'Authorization':'Bearer frontend-test-hfl-api-token'})
    assert documents.status_code == 200
    assert [doc['relative_path'] for doc in documents.json()['results']] == ['two.md', 'one.md']
    from bs4 import BeautifulSoup
    from urllib.parse import parse_qs, urlparse
    page = client.get('/hfl-corpus', params=state)
    toggle = BeautifulSoup(page.text, 'html.parser').find('a', {'aria-label':'Reverse primary sort direction'})
    assert parse_qs(urlparse(toggle['href']).query)['order_by'] == ['source DESC, entryDate DESC']
    from modules.hfl_shares.models import ShareConfiguration, ALL_SOURCES
    from modules.hfl_shares.scope import build_snapshot
    config = ShareConfiguration(id='', name='Ordered', recipient='Owner', sources=(ALL_SOURCES,),
        corpus_scope=ViewScope(any=[WorkspaceState()], all=WorkspaceState(**state)).model_dump_json())
    snapshot = build_snapshot(config, ordered_corpus)
    assert [entry.anchor for entry in snapshot.entries] == ['2', '1', '5', '3', '0', '4']


def test_feed_cursor_multiple_fields_and_equal_values(authenticated_client, workspace_corpus, monkeypatch):
    from modules.hfl_corpus.corpus import corpus_index
    rows = tuple(CorpusEntry(str(i).zfill(3), (datetime(2026, 1, 1) + timedelta(hours=i//2)).isoformat(),
        str(i), '', ('work',), 'alpha' if i % 3 else 'Zulu', f'Moment: {i}\nTags: #work') for i in range(108))
    doc = replace(workspace_corpus, entries=rows, entry_count=len(rows))
    monkeypatch.setattr(corpus_index, 'documents', lambda *a, **kw: (doc,))
    params = {'order_by':'source ASC, entryDate DESC'}
    results, cursor = [], None
    while True:
        response = authenticated_client.get('/hfl-corpus/curated-feed', params={**params, **({'cursor':cursor} if cursor else {})})
        assert response.status_code == 200
        data = response.json(); results.extend(entry['title'] for entry in data['entries'])
        cursor = data['next_cursor']
        if not cursor:
            break
    assert results == [row[2].moment for row in sorted_pairs(((doc, entry) for entry in rows), params['order_by'])]
    first = authenticated_client.get('/hfl-corpus/curated-feed', params=params).json()
    assert authenticated_client.get('/hfl-corpus/curated-feed', params={**params, 'order':'desc', 'cursor':first['next_cursor']}).status_code == 422


def test_order_by_browser_apply_and_space_persistence(editor_page, ordered_corpus):
    page, client = editor_page
    page.goto('https://editing.test/hfl-corpus?reset=1')
    panel = page.locator('[data-advanced-filters]')
    panel.locator('summary').click()
    panel.locator('[data-expression-toggle]').check()
    expect(panel.locator('[data-expression-apply]')).to_be_enabled()
    editor = panel.locator('[data-expression-editor]')
    editor.fill('ORDER BY source AS')
    editor.press('ArrowDown')
    editor.press('Enter')
    expect(editor).to_have_value('ORDER BY source ASC')
    editor.fill('ORDER BY source ASC, entryDate DESC')
    expect(page.locator('[name=order_by]')).to_have_value('source ASC, entryDate DESC')
    expect(page.locator('[name=sort]')).to_have_value('asc')
    expect(panel.locator('[data-order-summary]')).to_contain_text('source ASC, entryDate DESC')
    panel.locator('[data-expression-apply]').click()
    page.wait_for_url('**order_by=**')
    page.locator('[data-workspace-menu] > summary').click()
    page.locator('[data-manage-spaces]').click()
    page.locator('#space-destination').select_option('new')
    page.locator('#space-apply-draft').click()
    expect(page.locator('[data-edit-filter=order_by]')).to_have_value('source ASC, entryDate DESC')
    page.locator('#workspace-name').fill('Sorted sources')
    page.get_by_role('button', name='Save Space', exact=True).click()
    expect(page.locator('#space-status')).to_contain_text('Space saved')
    saved = next(v for v in client.get('/hfl-corpus/workspace-views').json()['views'] if v['name'] == 'Sorted sources')
    assert saved['state']['order_by'] == 'source ASC, entryDate DESC'
