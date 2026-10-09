from dataclasses import replace

import pytest
from playwright.sync_api import expect

from test_action_editing import editor_page
from test_corpus_workspaces import workspace_corpus
from test_hfl_ideas import ideas


def test_filtered_matching_entries_load(editor_page, workspace_corpus):
    page, _ = editor_page
    page.goto('https://editing.test/hfl-corpus?source=git,notes')
    summary = page.locator('summary').filter(has_text='2 matching entries')
    expect(summary).to_be_visible()
    summary.click()
    expect(page.locator('[data-matching-entry]')).to_have_count(2)
    summary.click()
    summary.click()
    expect(page.locator('[data-matching-entry]')).to_have_count(2)


@pytest.mark.parametrize('failure', ['server', 'network'])
def test_matching_entries_can_retry_failed_load(editor_page, workspace_corpus, failure):
    page, _ = editor_page
    endpoint = '**/hfl-corpus/matches/**'
    page.route(endpoint, lambda route: route.abort() if failure == 'network' else route.fulfill(status=502, body='Unavailable'))
    page.goto('https://editing.test/hfl-corpus?source=git,notes')
    page.locator('summary').filter(has_text='2 matching entries').click()
    panel = page.locator('[data-document-matches]')
    expect(panel).to_contain_text('Matching entries could not be loaded.')
    page.unroute(endpoint)
    panel.get_by_role('button', name='Retry', exact=True).click()
    expect(panel.locator('[data-matching-entry]')).to_have_count(2)


def test_matching_entries_pagination_stays_on_browser_origin(editor_page, workspace_corpus, monkeypatch):
    from modules.hfl_corpus import router

    entries = tuple(replace(workspace_corpus.entries[0], anchor=f'entry-{i}') for i in range(25))
    document = replace(workspace_corpus, entries=entries, entry_count=25)
    monkeypatch.setattr(router.corpus_index, 'documents', lambda: (document,))
    monkeypatch.setattr(router.corpus_index, 'get', lambda path: document)
    page, _ = editor_page
    page.goto('https://editing.test/hfl-corpus?source=git')
    page.locator('summary').filter(has_text='25 matching entries').click()
    expect(page.locator('[data-matching-entry]')).to_have_count(20)
    page.get_by_role('button', name='Load next 5', exact=True).click()
    expect(page.locator('[data-matching-entry]')).to_have_count(25)
    expect(page.locator('[data-matching-entry]').first).to_have_attribute('href', '/hfl-corpus/document/today.md#entry-0')
