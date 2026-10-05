"""Workspace unions and narrowing use original entry and document dates."""
import json
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from modules.hfl_corpus.entity_context import context_predicate
from modules.hfl_corpus.corpus import CorpusEntry


def test_union_with_tag_search_and_document_date_narrowing():
    context = urlencode({'scope': json.dumps({'any': [
        {'source': 'notes', 'q': '#project'}, {'source': 'meetings', 'q': 'planning'}]}),
        'date_field': 'updated', 'date_from': '2026-09-01', 'q': 'launch'})
    matches = context_predicate(context)
    document = SimpleNamespace(created_at=datetime(2025, 1, 1), updated_at=datetime(2026, 9, 20))
    def entry(source, text, tags=()):
        return CorpusEntry(anchor='one', header='2026-08-01', moment='', what_happened='',
                           tags=tags, source=source, text=text)
    assert matches(document, entry('notes', 'launch ready', ('project',)))
    assert matches(document, entry('meetings', 'planning the launch'))
    assert not matches(document, entry('notes', 'launch ready'))
    assert not matches(document, entry('meetings', 'planning later'))
    document.updated_at = datetime(2026, 8, 1)
    assert not matches(document, entry('meetings', 'planning the launch'))


def test_no_workspace_still_applies_source_and_query():
    matches = context_predicate(urlencode({'source': 'notes', 'q': '#project launch'}))
    document = SimpleNamespace()
    entry = CorpusEntry('one', '', '', '', ('project',), 'notes', 'launch ready')
    assert matches(document, entry)
    assert not matches(document, CorpusEntry('two', '', '', '', ('project',), 'email', 'launch ready'))
    assert context_predicate('') is None


@pytest.mark.parametrize('context', ['scope=invalid', 'rolling=oops', 'date_field=bogus', 'date_from=bad'])
def test_invalid_context_fails_closed(context):
    with pytest.raises(HTTPException) as error:
        context_predicate(context)
    assert error.value.status_code == 422


def test_graph_and_directory_pass_context_and_exclude_unrelated_profiles(monkeypatch, tmp_path):
    from modules.hfl_corpus import entities
    from modules.hfl_corpus import ideas_api
    monkeypatch.setattr(ideas_api, 'canonical_snapshot', lambda: {'ideas': [], 'actions': [], 'topics': [], 'links': []})
    from workflows.hfl.entity_store import get_store, VERSION
    monkeypatch.setenv('HARQIS_ENTITIES_DB', str(tmp_path / 'entities.sqlite3'))
    row = dict(id='one', title='Launch', text='React launch', source='notes', date='2026-09-20',
               tags=['project'], path='day.md', anchor='one')
    seen = []
    def current(context=''):
        seen.append(context)
        return [row]
    monkeypatch.setattr(entities, 'current_entries', current)
    mention = entities.mention(row, 'tools', 'React', 'React', 'model-extracted')
    store = get_store()
    store.save('one', entities.entry_hash(row), [mention], VERSION)
    store.save_profile('unrelated', 'tools', {'name':'Unrelated', 'categories':[]}, 'test')
    context = 'source=notes'
    assert entities.graph(context=context)['entries'] == 1
    assert [e['label'] for e in entities.entity_index(context=context)] == ['React']
    assert entities.entity_index(context=context, graph_query='missing') == []
    assert seen == [context, context, context]


def test_only_activity_modal_pages_allow_same_origin_frames(authenticated_client):
    for path in ['/hfl-corpus/graph', '/hfl-corpus/entities']:
        response = authenticated_client.get(path)
        assert response.status_code == 200
        assert response.headers['x-frame-options'] == 'SAMEORIGIN'
    assert authenticated_client.get('/login').headers['x-frame-options'] == 'DENY'
