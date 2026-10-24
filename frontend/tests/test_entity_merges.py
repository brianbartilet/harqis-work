"""Bulk identity changes preserve evidence, snapshots and retry semantics."""
from concurrent.futures import ThreadPoolExecutor
import json
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from modules.hfl_corpus import entities
from workflows.hfl.entity_store import get_store
from workflows.hfl import entity_merges


@pytest.fixture
def merge_data(monkeypatch, tmp_path):
    monkeypatch.setenv('HARQIS_ENTITIES_DB', str(tmp_path / 'entities.sqlite3'))
    rows = [dict(id=f'hfl-{i}', title=f'Entry {i}', text=f'Alex Alpha Beta {i}', source='notes',
                 date='2026-09-01', tags=[], path='day.md', anchor=str(i), ref='') for i in range(2)]
    monkeypatch.setattr(entities, 'current_entries', lambda: rows.copy())
    store = get_store()
    a = entities.mention(rows[0], 'people', 'Alex', 'Alex', 'model-extracted')
    b = entities.mention(rows[0], 'people', 'Alpha', 'Alpha', 'model-extracted')
    c = entities.mention(rows[1], 'people', 'Beta', 'Beta', 'model-extracted')
    store.save(rows[0]['id'], entities.entry_hash(rows[0]), [a, b])
    store.save(rows[1]['id'], entities.entry_hash(rows[1]), [{**a, 'evidence': 'Alex'}, c])
    for index, m in enumerate([a, b, c]):
        store.save_profile(m['id'], 'people', dict(name=m['label'], categories=['shared', str(index)],
            emails=['same@example.test', f'{index}@example.test'], phones=['+65 1234'],
            references=['https://example.test/common', f'https://example.test/{index}'], notes=f'Note {index}'))
    submitted = []
    def submit(entry, **kwargs):
        submitted.append((entry, kwargs))
        return {'delivery': 'outbox'}
    monkeypatch.setattr('workflows.hfl.persistence.submit_hfl_entry', submit)
    return rows, [a['id'], b['id'], c['id']], submitted


def submit_merge(client, ids, name='Unified', evidence='Same person'):
    body = dict(entity_ids=ids, name=name, evidence=evidence)
    preview = client.post('/api/hfl/entities/merge-preview', json=body)
    assert preview.status_code == 200, preview.text
    body.update(request_id=str(uuid4()), preview_token=preview.json()['preview_token'])
    response = client.post('/api/hfl/entities/merges', json=body)
    assert response.status_code == 200, response.text
    return response.json(), body, preview.json()


def test_bulk_merge_relations_profiles_audit_and_reversal(merge_data, authenticated_client):
    rows, ids, submitted = merge_data
    result, body, preview = submit_merge(authenticated_client, ids)
    merged_id = result['entity_id']
    assert preview['unique_entries'] == 2
    assert preview['profile']['categories'] == ['shared', '0', '1', '2']
    assert len(preview['profile']['emails']) == 4
    directory = entities.entity_index()
    assert len(directory) == 1 and directory[0]['id'] == merged_id
    assert len(directory[0]['entries']) == 2
    assert 'Alex' in directory[0]['entries'][0]['evidence'] and 'Alpha' in directory[0]['entries'][0]['evidence']
    graph = entities.graph(limit=0)
    assert len([e for e in graph['edges'] if e['target'] == merged_id]) == 2
    assert not any(n['id'] in ids for n in graph['nodes'])
    assert {m['label'] for e in entities.projection() for m in e['mentions']} == {'Unified'}
    assert len(submitted) == 1 and submitted[0][1]['source'] == 'entities-audit'
    assert submitted[0][0].what_happened.count('Same person') == 1
    assert authenticated_client.post('/api/hfl/entities/merges', json=body).json() == result
    assert len(submitted) == 1
    status = authenticated_client.get('/api/hfl/entities/operations/' + body['request_id']).json()
    assert status['state'] == 'complete' and status['audit_delivery']['delivery'] == 'outbox'
    profile = {**preview['profile'], 'notes': 'Edited after merging'}
    assert authenticated_client.post('/api/hfl/entities/profile/' + merged_id, json=profile).status_code == 200
    history = authenticated_client.get('/api/hfl/entities/audit/' + merged_id).json()['events']
    assert history[0]['action'] == 'profile-edited'
    reversal = dict(request_id=str(uuid4()), evidence='Separate again')
    undone = authenticated_client.post(f'/api/hfl/entities/merges/{merged_id}/unmerge', json=reversal)
    assert undone.status_code == 200 and set(undone.json()['restored_ids']) == set(ids)
    assert authenticated_client.post(f'/api/hfl/entities/merges/{merged_id}/unmerge', json=reversal).json() == undone.json()
    restored = entities.entity_index()
    assert {e['id'] for e in restored} == set(ids)
    assert {e['profile']['notes'] for e in restored} == {'Note 0', 'Note 1', 'Note 2'}
    events = authenticated_client.get('/api/hfl/entities/audit/' + ids[0]).json()['events']
    assert events[0]['data']['profile']['notes'] == 'Edited after merging'
    assert len(submitted) == 2


def test_nested_merges_reverse_outer_first(merge_data, authenticated_client):
    _, ids, _ = merge_data
    first, _, _ = submit_merge(authenticated_client, ids[:2], 'First')
    second, _, _ = submit_merge(authenticated_client, [first['entity_id'], ids[2]], 'Second')
    def undo(identity):
        return authenticated_client.post(f'/api/hfl/entities/merges/{identity}/unmerge', json={'request_id': str(uuid4())})
    assert undo(first['entity_id']).status_code == 409
    group_decision = next(d for d in get_store().decisions() if d['merge_id'] == second['entity_id'])
    assert authenticated_client.post(f"/api/hfl/entities/decisions/{group_decision['id']}/undo").status_code == 409
    assert undo(second['entity_id']).status_code == 200
    assert {e['id'] for e in entities.entity_index()} == {first['entity_id'], ids[2]}
    assert undo(first['entity_id']).status_code == 200
    assert {e['id'] for e in entities.entity_index()} == set(ids)


def test_validation_stale_previews_and_conflicting_retries(merge_data, authenticated_client):
    rows, ids, _ = merge_data
    store = get_store()
    store.save_profile('tool', 'tools', {'name': 'A tool'})
    path = '/api/hfl/entities/merge-preview'
    for selected in [[ids[0], 'tool'], [ids[0], 'missing'], [ids[0], ids[0]]]:
        assert authenticated_client.post(path, json={'entity_ids': selected, 'name': 'Test'}).status_code == 409
    body = dict(entity_ids=ids, name='Before')
    preview = authenticated_client.post(path, json=body).json()
    body.update(preview_token=preview['preview_token'], request_id=str(uuid4()))
    store.save_profile(ids[0], 'people', {'name': 'Changed'})
    assert authenticated_client.post('/api/hfl/entities/merges', json=body).status_code == 409
    result, body, _ = submit_merge(authenticated_client, ids)
    assert authenticated_client.post('/api/hfl/entities/merges', json={**body, 'name': 'Different'}).status_code == 409
    assert len([e for e in entities.entity_index() if e['kind'] == 'people']) == 1
    assert authenticated_client.post('/api/hfl/entities/profile/' + ids[0], json={'name': 'Hidden edit'}).status_code == 404
    assert result['state'] == 'complete'


def test_concurrent_commit_is_atomic_and_idempotent(merge_data):
    from modules.hfl_corpus.entity_merge_api import build_preview, MergePreview
    _, ids, _ = merge_data
    preview = build_preview(MergePreview(entity_ids=ids, name='Concurrent'))
    request_id = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: entity_merges.commit_merge(preview, request_id, 'same-body', 'test'), range(2)))
    assert results[0] == results[1]
    with get_store().connection() as db:
        assert db.execute('SELECT count(*) FROM entity_merges').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM entity_audit').fetchone()[0] == 1
    with pytest.raises(ValueError, match='changed'):
        entity_merges.commit_merge(preview, str(uuid4()), 'another-body', 'test')


def test_audit_delivery_failure_and_recovery(merge_data, authenticated_client, monkeypatch):
    _, ids, _ = merge_data
    monkeypatch.setattr('workflows.hfl.persistence.submit_hfl_entry', lambda *a, **k: (_ for _ in ()).throw(ConnectionError()))
    result, body, _ = submit_merge(authenticated_client, ids)
    status = authenticated_client.get('/api/hfl/entities/operations/' + body['request_id']).json()
    assert status['state'] == 'complete' and status['audit_delivery']['delivery'] == 'pending'
    sent = []
    monkeypatch.setattr('workflows.hfl.persistence.submit_hfl_entry', lambda entry, **kwargs: sent.append(kwargs['dedup_key']) or {'delivery': 'forwarded'})
    entity_merges.flush_audits()
    entity_merges.flush_audits()
    assert sent == ['entities-audit:' + result['event_id']]


def test_external_api_authentication_and_search(merge_data):
    from hfl_api import app
    _, ids, _ = merge_data
    with TestClient(app) as client:
        assert client.get('/api/hfl/entities').status_code == 401
        assert client.post('/api/hfl/entities/merge-preview', json={'entity_ids': ids, 'name': 'Test'}).status_code == 401
        client.headers['Authorization'] = 'Bearer wrong'
        assert client.get('/api/hfl/entities').status_code == 401
        client.headers['Authorization'] = 'Bearer frontend-test-hfl-api-token'
        data = client.get('/api/hfl/entities?q=Alex&kind=people&limit=1').json()
        assert data['total'] == 1 and data['counts']['people'] == 3
        result, body, _ = submit_merge(client, ids)
        assert client.get('/api/hfl/entities/audit/' + result['entity_id']).json()['events'][0]['actor'] == 'owner-api'
        assert client.get('/api/hfl/entities/operations/' + body['request_id']).status_code == 200


def test_large_profiles_are_not_truncated(merge_data, authenticated_client):
    _, ids, _ = merge_data
    for index, identity in enumerate(ids):
        profile = dict(name=f'Name {index}', categories=[f'c-{index}-{i}' for i in range(25)],
                       references=[f'https://example.test/{index}/{i}' for i in range(60)], notes='x' * 12000)
        assert authenticated_client.post('/api/hfl/entities/profile/' + identity, json=profile).status_code == 200
    result, _, preview = submit_merge(authenticated_client, ids)
    assert len(preview['profile']['categories']) == 75
    assert len(preview['profile']['references']) == 180
    assert len(preview['profile']['notes']) > 36000
    assert authenticated_client.post('/api/hfl/entities/profile/' + result['entity_id'], json=preview['profile']).status_code == 200


def test_reviewed_profile_edits_are_saved_atomically(merge_data, authenticated_client):
    _, ids, _ = merge_data
    body = dict(entity_ids=ids, name='Reviewed identity')
    preview = authenticated_client.post('/api/hfl/entities/merge-preview', json=body).json()
    body.update(request_id=str(uuid4()), preview_token=preview['preview_token'], profile={
        'categories': [' Employee ', 'Employee'], 'emails': ['not-an-email'],
        'references': [], 'notes': 'User revised the combined notes',
    })
    assert authenticated_client.post('/api/hfl/entities/merges', json=body).status_code == 400
    assert {e['id'] for e in entities.entity_index()} == set(ids)
    body['profile']['emails'] = ['employee@example.test']
    response = authenticated_client.post('/api/hfl/entities/merges', json=body)
    assert response.status_code == 200
    identity = response.json()['entity_id']
    profile = get_store().profiles()[identity]
    assert profile['categories'] == ['Employee']
    assert profile['emails'] == ['employee@example.test']
    assert profile['references'] == []
    assert profile['phones'] == preview['profile']['phones']  # Omitted fields keep the proposed values.
    assert profile['notes'] == body['profile']['notes']
    assert authenticated_client.post('/api/hfl/entities/merges', json=body).json() == response.json()
    assert entity_merges.history(identity)[0]['data']['profile']['notes'] == profile['notes']
    assert authenticated_client.post(f'/api/hfl/entities/merges/{identity}/unmerge', json={'request_id': str(uuid4())}).status_code == 200
    assert {get_store().profiles()[i]['notes'] for i in ids} == {'Note 0', 'Note 1', 'Note 2'}


def test_large_alias_union_merges_with_reviewed_fields_and_remains_editable(merge_data, authenticated_client):
    _, ids, _ = merge_data
    store = get_store()
    for index, identity in enumerate(ids[:2]):
        profile = store.profiles()[identity]
        store.save_profile(identity, 'people', {**profile, 'aliases': [f'Alias {index}-{n}' for n in range(70)]})
    body = dict(entity_ids=ids[:2], name='HARQIS', evidence='Reviewed aliases')
    preview = authenticated_client.post('/api/hfl/entities/merge-preview', json=body)
    assert preview.status_code == 200, preview.text
    expected = preview.json()['profile']['aliases']
    assert len(expected) > 100
    body.update(request_id=str(uuid4()), preview_token=preview.json()['preview_token'], profile={'preferred_name': True})
    response = authenticated_client.post('/api/hfl/entities/merges', json=body)
    assert response.status_code == 200, response.text
    identity = response.json()['entity_id']
    profile = store.profiles()[identity]
    assert profile['aliases'] == expected
    assert authenticated_client.post('/api/hfl/entities/profile/' + identity, json=profile).status_code == 200
    assert authenticated_client.post('/api/hfl/entities/merges', json=body).json() == response.json()


def test_oversized_alias_union_is_rejected_at_preview(merge_data, authenticated_client):
    _, ids, _ = merge_data
    store = get_store()
    for index, identity in enumerate(ids[:2]):
        store.save_profile(identity, 'people', {**store.profiles()[identity],
            'aliases': [f'Alias {index}-{n}' for n in range(6000)]})
    response = authenticated_client.post('/api/hfl/entities/merge-preview',
        json=dict(entity_ids=ids[:2], name='HARQIS'))
    assert response.status_code == 409
    assert '10000' in response.json()['detail']
