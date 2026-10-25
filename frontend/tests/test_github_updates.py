"""PR intake exercises real journals, actions and links against bounded API doubles."""
import json
from uuid import uuid4

import pytest
from fastapi import HTTPException
from modules.integrations import github_updates as subject, service, store
from modules.integrations.github_updates_store import Inbox
from modules.hfl_corpus import workspace_views
from modules.hfl_corpus.timeline import store as actions

USER = 'frontend-test-user'


def pr(number=1, **changes):
    return dict(id=1000 + number, number=number, title='Reviewable work', body='Evidence',
        state='open', draft=False, created_at='2026-10-01T00:00:00Z', updated_at='2026-10-25T00:00:00Z',
        user={'login': 'bot[bot]'}, head={'ref': 'feature/test', 'repo': {'full_name': 'fork/demo'}},
        base={'ref': 'main', 'repo': {'full_name': 'owner/demo'}}, **changes)


@pytest.fixture
def intake(monkeypatch, tmp_path):
    monkeypatch.setenv('HARQIS_CONNECTORS_DB', str(tmp_path / 'connectors.sqlite3'))
    monkeypatch.setenv('HFL_TIMELINE_LOCAL_PREVIEW', '1')
    with workspace_views.connection() as db:
        workspace_views.schema(db)
        db.execute('DELETE FROM corpus_workspace_views')
    space = workspace_views.save(workspace_views.WorkspaceWrite(name='peon', state=workspace_views.WorkspaceState(source='git', q='keep me')))
    store.save(USER, 'github', {'enabled': True, 'status': 'Connected', 'account_id': '42'}, {'token': 'test-only'})
    state = {'prs': [pr()], 'calls': [], 'receipts': [], 'indexed': True, 'fail': False}

    def request(self, method, path, *, params=None, **kwargs):
        assert method == 'GET'
        state['calls'].append((path, params))
        if state['fail']:
            raise HTTPException(429, 'Rate limited')
        if path == '/user/repos':
            return [{'full_name': 'owner/demo'}]
        if path.endswith('/pulls'):
            start = (params['page'] - 1) * params['per_page']
            return state['prs'][start:start + params['per_page']]
        return next(row for row in state['prs'] if str(row['number']) == path.rsplit('/', 1)[-1])

    def persist(value):
        state['receipts'].append(value)
        return {'delivery': 'persisted', 'indexed': state['indexed'], 'entry_id': 'hfl-pr-' + value['identity'], 'path': 'unused'}

    monkeypatch.setattr(service.Provider, 'request', request)
    monkeypatch.setattr(subject, 'persist_entry', persist)
    monkeypatch.setattr(subject, 'action_source', lambda pr, receipt: {'entry_id': receipt['entry_id'], 'path': '2026-10-01.md', 'title': pr['title'], 'date': '2026-10-01'})
    state.update(space=space, inbox=Inbox(USER + '::42'))
    yield state
    with workspace_views.connection() as db:
        for table in ('corpus_workspace_views', 'corpus_workspace_last', 'corpus_view_preferences', 'corpus_view_schedules'):
            db.execute('DELETE FROM ' + table)


def test__backfill_replay_preserves_one_entry_action_and_fork_link(intake):
    first = subject.run(pages=5)
    assert first['discovery_complete'] and first['tracked'] == 1 and first['pending'] == 0
    item = actions().get(first['action_ids'][0])
    assert item['agent_enabled'] is False and item['status'] == 'open'
    assert item['workspace_ids'] == [intake['space']['id']]
    link = store.links(USER, 'github')[0]
    assert (link['repository'], link['head_repository'], link['branch'], link['base'], link['pr_number']) == ('owner/demo', 'fork/demo', 'feature/test', 'main', 1)
    assert item['source']['entry_id'] == 'hfl-pr-1001'
    second = subject.run(pages=5)
    assert second['applied'] == 0 and len(actions().list()) == 1
    assert len(intake['receipts']) == 1
    view = next(v for v in workspace_views.listing()['views'] if v['id'] == intake['space']['id'])
    assert view['state']['source'] == 'git,github-updates' and view['state']['q'] == 'keep me'


def test__draft_waits_until_published(intake):
    intake['prs'][0]['draft'] = True
    assert subject.run()['tracked'] == 0
    intake['prs'][0]['draft'] = False
    assert subject.run()['tracked'] == 1


def test__indexing_failure_blocks_action_then_recovers(intake):
    intake['indexed'] = False
    result = subject.run()
    assert result['status'] == 'partial' and result['pending'] == 1 and not actions().list()
    intake['indexed'] = True
    assert subject.run()['pending'] == 0
    assert len(actions().list()) == 1


def test__link_failure_after_action_creation_recovers_same_action(intake, monkeypatch):
    original = store.link
    monkeypatch.setattr(store, 'link', lambda *args: (_ for _ in ()).throw(OSError('disk unavailable')))
    assert subject.run()['pending'] == 1
    identity = actions().list()[0]['id']
    monkeypatch.setattr(store, 'link', original)
    assert subject.run()['pending'] == 0
    assert [x['id'] for x in actions().list()] == [identity]


def test__existing_link_is_reused_and_user_content_preserved(intake):
    item, _ = actions().create({'request_id': str(uuid4()), 'title': 'My edited review', 'notes': 'Keep this', 'agent_enabled': False}, actor='owner')
    store.link(USER, 'github', 'existing', {'account_key': ':42', 'action_id': item['id'], 'repository': 'owner/demo', 'pr_number': 1})
    assert subject.run()['action_ids'] == [item['id']]
    assert len(actions().list()) == 1
    assert actions().get(item['id'])['notes'] == 'Keep this'
    assert store.links(USER, 'github')[0]['resource'] == 'existing'


def test__ambiguous_action_write_replays_immutable_request(intake, monkeypatch):
    from workflows.hfl.timeline_store import FollowUpStore
    original = FollowUpStore.create
    failed = []
    def create(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if not failed:
            failed.append(True)
            raise TimeoutError('Response lost after commit')
        return result
    monkeypatch.setattr(FollowUpStore, 'create', create)
    assert subject.run()['pending'] == 1
    identity = actions().list()[0]['id']
    intake['prs'][0]['title'] = 'Upstream title changed during retry'
    assert subject.run()['pending'] == 0
    assert [item['id'] for item in actions().list()] == [identity]


@pytest.mark.parametrize('state,merged,target', [('closed', None, 'dismissed'), ('closed', '2026-10-25T01:00:00Z', 'done')])
def test__closure_and_reopening_preserve_terminal_decision(intake, state, merged, target):
    identity = subject.run()['action_ids'][0]
    intake['prs'][0].update(state=state, merged_at=merged)
    value = subject.snapshot('owner/demo', intake['prs'][0])
    intake['inbox'].observe(value)
    subject.run(pages=1)
    assert actions().get(identity)['status'] == target
    intake['prs'][0].update(state='open', merged_at=None)
    intake['inbox'].observe(subject.snapshot('owner/demo', intake['prs'][0]))
    subject.run(pages=1)
    assert actions().get(identity)['status'] == target


def test__pagination_resumes_and_does_not_cap_at_first_page(intake):
    intake['prs'] = [pr(i) for i in range(1, 103)]
    assert not subject.run(pages=1, limit=1)['discovery_complete']
    assert subject.run(pages=1, limit=1)['tracked'] == 100
    assert subject.run(pages=1, limit=1)['tracked'] == 102
    result = subject.run(pages=1, limit=1)
    assert result['discovery_complete'] and result['pending'] == 99


def test__lease_prevents_overlapping_runs(intake):
    lease = intake['inbox'].acquire()
    assert subject.run()['status'] == 'busy'
    assert not intake['calls']
    intake['inbox'].release(lease)
    assert subject.run()['status'] == 'complete'


def test__rate_limit_keeps_cursor_and_releases_lease(intake):
    intake['fail'] = True
    with pytest.raises(HTTPException) as failure:
        subject.run()
    assert failure.value.status_code == 429
    assert intake['inbox'].cursor() == {}
    intake['fail'] = False
    assert subject.run()['status'] == 'complete'


def test__missing_or_ambiguous_workspace_blocks_writes(intake):
    workspace_views.save(workspace_views.WorkspaceWrite(name='Peon', state=workspace_views.WorkspaceState()))
    with pytest.raises(ValueError, match='Exactly one'):
        subject.run()
    assert not intake['calls'] and not actions().list()


def test__empty_source_selection_remains_all_sources(intake):
    with workspace_views.connection() as db:
        db.execute('UPDATE corpus_workspace_views SET state=? WHERE id=?', (json.dumps({'source': ''}), intake['space']['id']))
    subject.run()
    assert workspace_views.listing()['views'][0]['state']['source'] == ''


def test__api_requires_bearer_and_bounds_work(intake, authenticated_client):
    path = '/api/hfl/github-updates/sync'
    assert authenticated_client.post(path, json={}).status_code == 401
    headers = {'Authorization': 'Bearer frontend-test-hfl-api-token'}
    assert authenticated_client.post(path, json={'pages': 999}, headers=headers).status_code == 422
    result = authenticated_client.post(path, json={}, headers=headers)
    assert result.status_code == 200 and result.json()['tracked'] == 1


def test__fork_card_can_refresh_and_link_existing_pr(intake):
    identity = subject.run()['action_ids'][0]
    link = store.links(USER, 'github')[0]
    assert service.github_pr(USER, identity, {'resource': link['resource'], 'number': 1})['pr_number'] == 1
    assert service.refresh_github(USER, identity)[0]['head_repository'] == 'fork/demo'


def test__disabled_connector_does_not_import(intake):
    store.save(USER, 'github', {'enabled': False, 'status': 'Connected', 'account_id': '42'})
    with pytest.raises(HTTPException) as failure:
        subject.run()
    assert failure.value.status_code == 409 and not intake['calls']


def test__actual_entry_keeps_tags_reference_and_identity(monkeypatch, tmp_path):
    from workflows.hfl import es_store, entity_events
    from modules.hfl_corpus import corpus
    monkeypatch.setattr(corpus, 'resolve_corpus_root', lambda: tmp_path)
    monkeypatch.setattr(es_store, 'index_hfl_entry', lambda entry, **kwargs: entry.entry_id)
    monkeypatch.setattr(entity_events, 'notify_change', lambda identity: None)
    value = subject.snapshot('owner/demo', pr())
    one, two = subject.persist_entry(value), subject.persist_entry(value)
    assert one['entry_id'] == two['entry_id'] and two['duplicate']
    text = __import__('pathlib').Path(one['path']).read_text(encoding='utf-8')
    assert text.count('Entry ID:') == 1 and 'github-updates' in text
    assert all('#' + tag in text for tag in subject.TAGS)
    assert value['url'] in text


def test__provider_preserves_rate_limit_delay(monkeypatch):
    import httpx
    from modules.integrations.providers import Provider
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def request(self, *args, **kwargs):
            return httpx.Response(429, headers={'Retry-After': '600'}, request=httpx.Request('GET', 'https://api.github.com/user/repos'))
    monkeypatch.setattr(httpx, 'Client', Client)
    with pytest.raises(HTTPException) as failure:
        Provider('github', {'token': 'test-only'}).request('GET', '/user/repos')
    assert failure.value.headers == {'Retry-After': '600'}
