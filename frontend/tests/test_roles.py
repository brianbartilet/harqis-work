"""Personal context must remain explicitly scoped and immutable after publication."""
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import FormData

from modules.roles import store, sharing, audit
from modules.hfl_shares.models import ShareConfiguration, ScopeSnapshot
from modules.hfl_shares.scope import build_snapshot
from modules.hfl_shares.security import make_csrf_token


@pytest.fixture(autouse=True)
def isolated_roles(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'get_profile_store', lambda: SimpleNamespace(path=tmp_path/'roles.sqlite3'))


def role(**changes):
    return store.save(None, 0, dict(name='Programmer', color='#38bdf8', soul='## Public\nBuilt test tools.\n\n## Private\nPersonal phone 123.', workspace_ids=[], entity_ids=[], archived=False, **changes))


def config(persona):
    return ShareConfiguration(id='recipe', name='Interview', recipient='Hiring manager', sources=('__all__',), persona=persona)


def test_selected_sections_are_citable_and_frozen():
    owner = role()
    options = sharing.choices()
    selected = sharing.from_form(FormData([('persona_ids', options[0]['id'])]))
    cfg = config(selected)
    snapshot = build_snapshot(cfg, ())
    assert len(snapshot.all_entries) == 1
    assert 'Built test tools' in snapshot.all_entries[0].text
    assert 'phone' not in json.dumps(snapshot.to_record())
    store.save(owner['id'], owner['revision'], {'soul': 'New private details'})
    assert build_snapshot(cfg, ()).persona_entries == snapshot.persona_entries
    assert ScopeSnapshot.from_record(snapshot.to_record()) == snapshot


def test_stale_selection_and_role_edits_fail_closed():
    owner = role()
    token = sharing.choices()[0]['id']
    store.save(owner['id'], 1, {'soul': 'Changed'})
    with pytest.raises(ValueError, match='changed'):
        sharing.from_form(FormData([('persona_ids', token)]))
    with pytest.raises(HTTPException) as error:
        store.save(owner['id'], 1, {'soul': 'Lost update'})
    assert error.value.status_code == 409
    assert len(store.history(owner['id'])) == 2


def test_journal_and_archive_are_private_by_default():
    owner = role()
    journal = [{'id':'n1','text':'Unreviewed inference','status':'pending','evidence':[]},
               {'id':'n2','text':'Approved observation','status':'approved','evidence':[{'path':'private-path'}]}]
    owner = store.save(owner['id'], 1, {'journal':journal})
    serialized = json.dumps(sharing.choices())
    assert 'Unreviewed inference' not in serialized and 'private-path' not in serialized
    assert 'Approved observation' in serialized
    store.save(owner['id'], owner['revision'], {'archived': True})
    assert sharing.choices() == []


def test_owner_auth_csrf_and_markdown(authenticated_client):
    client = authenticated_client
    assert client.post('/roles/data', json={'name':'Tester'}).status_code == 403
    headers = {'X-CSRF-Token': make_csrf_token('frontend-test-user')}
    response = client.post('/roles/data', headers=headers, json={'name':'Tester'})
    assert response.status_code == 200, response.text
    assert client.get('/roles').status_code == 200
    rendered = client.post('/roles/markdown', headers=headers, json={'text':'<script>alert(1)</script>\n\n**Safe**'}).json()['html']
    assert '<script>' not in rendered and '<strong>Safe</strong>' in rendered
    client.cookies.clear()
    assert client.get('/roles/data').status_code == 401
    assert client.get('/api/hfl/roles').status_code == 401


def test_audit_incremental_deduplicated_and_no_soul_rewrite(monkeypatch):
    owner = role()
    store.save(owner['id'], 1, {'workspace_ids':['space']})
    rows = [{'id':'e1','title':'Testing','text':'Built tests','source':'notes','path':'day.md','anchor':'entry'}]
    monkeypatch.setattr(audit, 'evidence', lambda role: rows)
    calls = []
    monkeypatch.setattr(audit, 'analyze', lambda role, rows: calls.append(rows) or {'observations':[{'text':'Consider documenting the testing work.','evidence_ids':['e1']}]})
    receipts = []
    monkeypatch.setattr(audit, 'report', lambda run: receipts.append(run['id']))
    first = audit.run('manual-1')
    assert first['status'] == 'complete'
    audit.run('manual-1')
    audit.run('manual-2')
    assert len(calls) == 1 and receipts == ['manual-1', 'manual-2']
    current = store.get(owner['id'])
    assert current['soul'] == owner['soul']
    assert len(current['journal']) == 1 and current['journal'][0]['status'] == 'pending'


def test_audit_rejects_invented_citations_and_retries_report(monkeypatch):
    owner = role()
    store.save(owner['id'], 1, {'workspace_ids':['space']})
    monkeypatch.setattr(audit, 'evidence', lambda role: [{'id':'e1','title':'A','text':'A','source':'notes','path':'a','anchor':'a'}])
    monkeypatch.setattr(audit, 'analyze', lambda *args: {'observations':[{'text':'Unsupported','evidence_ids':['other-role']}]})
    def unavailable(run):
        raise OSError('offline')
    monkeypatch.setattr(audit, 'report', unavailable)
    result = audit.run('bad-run')
    assert result['status'] == 'failed' and result['report_pending']
    assert not store.get(owner['id'])['journal']


def test_live_citations_do_not_collide_with_persona():
    from modules.hfl_shares.router import _stable_live_citations
    from modules.hfl_shares.models import SnapshotEntry
    e = SnapshotEntry('a','S1','','','','','','',(), 'activity')
    p = replace(e, id='p', citation='S2', source='persona')
    old = ScopeSnapshot((e,), 'now', (), {}, {}, persona_entries=(p,))
    new = replace(old, entries=(replace(e,id='new'),e), persona_entries=(replace(p,citation='S3'),))
    stable = _stable_live_citations(new, old)
    assert [v.citation for v in stable.all_entries] == ['S3','S1','S2']
