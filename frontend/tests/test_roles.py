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
from test_action_editing import editor_page
from test_hfl_ideas import ideas
from test_hfl_shares import sharing_corpus
from test_workspace_sharing import context


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


def test_revision_and_analysis_context_are_explicit_and_frozen():
    owner = role()
    owner = store.save(owner['id'], 1, {'soul': '', 'journal': [
        {'id': 'private', 'status': 'pending', 'text': 'Unapproved inference'},
        {'id': 'approved', 'status': 'approved', 'text': 'Built Python test tooling'},
    ]})
    store.record_run({'id': 'run', 'created_at': '2026-10-11', 'status': 'complete',
        'roles': [{'id': owner['id'], 'selected': 62, 'observations': 12, 'coverage': '651 deferred'}]})
    options = sharing.choices()
    assert 'Unapproved inference' not in json.dumps(options)
    selected = sharing.from_form(FormData([('persona_ids', item['id']) for item in options
        if item['origin'] in {'Revision history', 'Analysis history', 'Agent observation, owner-approved'}]))
    snapshot = build_snapshot(config(selected), ())
    from modules.hfl_shares.agent import _context
    text = _context(snapshot, entries=())
    assert 'Built test tools' in text and 'Built Python test tooling' in text
    assert '62 new or changed sources' in text and '651 deferred' in text
    store.save(owner['id'], 2, {'soul': 'New unshared revision'})
    assert build_snapshot(config(selected), ()).persona_entries == snapshot.persona_entries
    assert not build_snapshot(config({}), ()).persona_entries


def test_owner_agent_can_read_revisions_with_bearer_auth(authenticated_client):
    owner = role()
    store.save(owner['id'], 1, {'soul': 'Updated Soul'})
    url = f"/api/hfl/roles/{owner['id']}/history"
    assert authenticated_client.get(url).status_code == 401
    result = authenticated_client.get(url, headers={'Authorization': 'Bearer frontend-test-hfl-api-token'})
    assert result.status_code == 200
    assert [item['revision'] for item in result.json()['history']] == [2, 1]
    assert result.json()['history'][1]['soul'].startswith('## Public')


def test_linked_entity_activity_becomes_selected_share_evidence(monkeypatch, context, sharing_corpus):
    from modules.hfl_shares import activity, personalization, router
    python = {'id': 'tool:python', 'label': 'Python', 'kind': 'tools', 'count': 1}
    monkeypatch.setattr(personalization, 'entity_catalog', lambda: [python])
    monkeypatch.setattr(router, '_sharing_documents', lambda *args: (sharing_corpus,))
    monkeypatch.setattr(activity, 'mentions_for_documents', lambda docs: [
        {'id': 'hfl-share-test', 'mentions': [python]}])
    owner = role()
    store.save(owner['id'], 1, {'entity_ids': ['tool:python']})
    options = [item for item in sharing.choices() if item['origin'] == 'Linked entity activity']
    assert len(options) == 1
    assert 'Linked entities: Python' in options[0]['text']
    assert 'private-host' not in options[0]['text']
    assert 'Secret-backed action' not in str(options)
    selected = sharing.from_form(FormData([('persona_ids', options[0]['id'])]))
    snapshot = build_snapshot(config(selected), ())
    from modules.hfl_shares.agent import _context
    assert 'Booked Kyoto accommodation' in _context(snapshot, 'Python', entries=())
    assert 'Python' in _context(snapshot, 'Python', entries=())
    assert not snapshot.persona_entries[0].references


@pytest.mark.parametrize('width', [1440, 390])
def test_role_history_and_attachment_layout(editor_page, monkeypatch, width, tmp_path):
    from playwright.sync_api import expect
    from modules.hfl_shares import personalization
    monkeypatch.setattr(personalization, 'entity_catalog', lambda: [])
    owner = role()
    owner = store.save(owner['id'], 1, {'soul': '', 'files': [
        {'id': 'cv', 'name': 'Career history.pdf', 'status': 'ready', 'text': 'Career', 'digest': 'test'}]})
    store.record_run({'id': 'run', 'created_at': '2026-10-11T01:00:00Z', 'status': 'complete',
        'roles': [{'id': owner['id'], 'name': owner['name'], 'selected': 62, 'observations': 12,
                   'coverage': '90-day entries; 651 sources deferred'}]})
    page, client = editor_page
    page.set_viewport_size({'width': width, 'height': 1000})
    page.goto('https://editing.test/roles')
    page.locator(f'#roles-list [data-role="{owner["id"]}"]').click()
    page.locator('[data-pane=history]').click()
    revision = page.locator('#role-history details').first
    revision.locator('summary').click()
    expect(revision).to_contain_text('No Soul text saved in this revision.')
    expect(revision).to_contain_text('Career history.pdf')
    expect(revision).to_contain_text('Linked entities')
    page.screenshot(path=str(tmp_path / f'roles-revisions-{width}.png'), full_page=True)
    page.locator('[data-pane=files]').click()
    expect(page.locator('.role-file-status .role-run-badge')).to_have_text('Ready')
    a, b = [button.bounding_box() for button in page.locator('.role-file-actions button').all()]
    assert b['x'] >= a['x'] + a['width'] + 7
    page.locator('aside summary').filter(has_text='Analysis history').click()
    page.get_by_text('Run details', exact=True).click()
    coverage = page.locator('.role-run-result .role-help').bounding_box()
    journal = page.locator('.role-run-result button').bounding_box()
    assert journal['y'] >= coverage['y'] + coverage['height'] + 11
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(tmp_path / f'roles-spacing-{width}.png'), full_page=True)


def test_chat_includes_all_approved_cv_excerpts_beyond_retrieval_limit(monkeypatch):
    import asyncio
    from modules.hfl_shares import agent

    owner = role()
    # More excerpts than the normal eight search results; early career is last.
    text = ''.join(f'Employment period {i}.'.ljust(3000, ' ') for i in range(10))
    store.save(owner['id'], 1, {'files': [
        {'id': 'cv', 'name': 'cv.txt', 'digest': 'digest', 'status': 'ready',
         'text': text + 'Private unselected details.'},
    ]})
    options = [item for item in sharing.choices() if item.get('file')]
    selected = sharing.from_form(FormData([
        ('persona_ids', item['id']) for item in options[:10]
    ]))
    snapshot = build_snapshot(config(selected), ())
    captured = {}

    async def answer(**kwargs):
        captured.update(kwargs)
        return 'Career includes [[Employment period 9|S10]].'

    monkeypatch.setattr(agent, 'get_settings', lambda: SimpleNamespace(
        hfl_share_provider='hermes', hfl_share_max_context_chars=120000))
    monkeypatch.setattr(agent, 'retrieve_entries', lambda *args, **kwargs: snapshot.persona_entries[:1])
    monkeypatch.setattr(agent, '_answer_with_hermes', answer)
    result = asyncio.run(agent.answer_question(snapshot, 'Describe the full employment history'))
    assert 'Employment period 9' in result
    for i in range(10):
        assert f'Employment period {i}.' in captured['user']
    assert captured['user'].count('citation="[S1]"') == 1
    assert 'Private unselected details' not in captured['user']
    assert 'Personal phone' not in captured['user']


def test_chat_context_reports_omissions_and_keeps_smaller_entries(monkeypatch):
    from modules.hfl_shares import agent
    from modules.hfl_shares.models import SnapshotEntry

    large = SnapshotEntry('large', 'S1', '', '', '', '', '', 'persona', (), 'x' * 6000)
    small = replace(large, id='small', citation='S2', text='Earlier employment history')
    snapshot = ScopeSnapshot((), 'now', (), {}, {}, {}, persona_entries=(large, small))
    monkeypatch.setattr(agent, 'get_settings', lambda: SimpleNamespace(hfl_share_max_context_chars=5000))
    context = agent._context(snapshot, entries=(large,))
    assert 'Earlier employment history' in context
    assert 'context size limit' in context
    assert 'citation="[S1]"' not in context


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
    e = SnapshotEntry('a','S1','','','','','', 'notes', (), 'activity')
    p = replace(e, id='p', citation='S2', source='persona')
    old = ScopeSnapshot((e,), 'now', (), {}, {}, {}, persona_entries=(p,))
    new = replace(old, entries=(replace(e,id='new'),e), persona_entries=(replace(p,citation='S3'),))
    stable = _stable_live_citations(new, old)
    assert [v.citation for v in stable.all_entries] == ['S3','S1','S2']


def test_attachment_excerpts_and_original_download_are_separate(authenticated_client):
    from modules.hfl_shares.router import _download_response
    owner = role()
    headers = {'X-CSRF-Token':make_csrf_token('frontend-test-user')}
    response = authenticated_client.post('/roles/data/'+owner['id']+'/attachments', headers=headers,
                                         files={'files':('cv.txt', b'Testing experience. Private contact details.', 'text/plain')})
    assert response.status_code == 200, response.text
    file = response.json()['files'][0]
    assert file['status'] == 'ready'
    option = next(o for o in sharing.choices() if o.get('file'))
    selected = sharing.from_form(FormData([('persona_ids', option['id'])]))
    snapshot = build_snapshot(config(selected), ())
    assert not snapshot.persona_entries[0].references
    selected = sharing.from_form(FormData([('persona_ids', option['id']), ('persona_downloads', option['id'])]))
    snapshot = build_snapshot(config(selected), ())
    grant = SimpleNamespace(snapshot=snapshot)
    reference = snapshot.persona_entries[0].references[0]
    response = _download_response(grant, reference.id)
    assert response.filename == 'cv.txt'
    with pytest.raises(HTTPException):
        _download_response(grant, 'unapproved-reference')
    owner = store.get(owner['id'])
    authenticated_client.post(f"/roles/data/{owner['id']}/attachments/{file['id']}/detach", headers=headers, json={'revision':owner['revision']})
    assert not any(o.get('file') for o in sharing.choices())
    assert _download_response(grant, reference.id).filename == 'cv.txt'


def test_role_editor_and_sharing_preview_browser(editor_page, sharing_corpus, tmp_path):
    from playwright.sync_api import expect
    page, client = editor_page
    page.goto('https://editing.test/roles')
    page.locator('#role-new').click()
    page.get_by_label('Facet name', exact=True).fill('Programmer and tester')
    page.locator('[name=soul]').fill('## Experience\nBuilt reliable testing tools.\n\n## Private\nPrivate family detail.')
    page.get_by_role('button', name='Save facet', exact=True).click()
    expect(page.locator('#role-status')).to_contain_text('Facet saved')
    expect(page.locator('#role-preview')).to_have_count(0)
    expect(page.locator('#role-revision')).to_have_count(0)
    expect(page.locator('#role-colors button')).not_to_have_count(0)
    expect(page.locator('#role-markdown')).to_contain_text('Built reliable testing tools')
    page.goto('https://editing.test/sharing')
    expect(page.locator('[name=persona_ids]')).to_have_count(2)
    assert page.locator('[name=persona_ids]:checked').count() == 0
    # The approved excerpt is the only personal material in the snapshot.
    options = sharing.choices()
    token = next(o['id'] for o in options if o['title'] == 'Experience')
    headers = {'X-CSRF-Token':make_csrf_token('frontend-test-user')}
    data = {'csrf':make_csrf_token('frontend-test-user'), 'name':'Interview', 'recipient':'Recruiter',
            'sources':'__all__', 'persona_ids':token, 'persona_company':'Example Co'}
    result = client.post('/sharing/preview', data=data, headers=headers)
    assert result.status_code == 200, result.text[:500]
    assert 'approved personal context (1 excerpts)' not in result.text
    assert 'Built reliable testing tools' in result.text
    # Private text may remain in the owner's selection catalog, never the snapshot.
    selected = sharing.from_form(FormData([('persona_ids', token)]))
    assert 'Private family detail' not in json.dumps(build_snapshot(config(selected), ()).to_record())


def test_docx_and_empty_pdf_extraction(tmp_path):
    from modules.roles.extraction import extract
    from docx import Document
    from pypdf import PdfWriter
    doc = Document()
    doc.add_paragraph('Testing career history')
    doc.add_table(rows=1, cols=1).cell(0,0).text = 'Automation engineer'
    path = tmp_path/'cv.docx'
    doc.save(path)
    assert 'Automation engineer' in extract(path, path.name)['text']
    empty_pdf = tmp_path/'scan.pdf'
    writer = PdfWriter(); writer.add_blank_page(width=100, height=100)
    writer.write(empty_pdf)
    with pytest.raises(ValueError, match='No readable text'):
        extract(empty_pdf, empty_pdf.name)


def test_guest_persona_is_frozen_until_explicit_recipe_update(authenticated_client, monkeypatch):
    from test_share_guest_views import make_share
    from modules.hfl_shares.store import get_share_store
    from modules.hfl_shares import router
    owner = role()
    choice = sharing.choices()[0]
    cfg = get_share_store().save_configuration(replace(config(sharing.from_form(FormData([('persona_ids',choice['id'])]))), live_updates=True))
    grant = make_share(build_snapshot(cfg, ()), cfg)
    monkeypatch.setattr(router, '_sharing_documents', lambda *args, **kw: ())
    store.save(owner['id'], 1, {'soul':'## Updated\nA new achievement.'})
    page = authenticated_client.get('/sharing/shares/'+grant.id+'/preview')
    assert page.status_code == 200
    assert 'data-share-view="about"' not in page.text and 'Built test tools' not in page.text
    assert '<summary>About the sharer</summary>' not in page.text
    assert 'A new achievement' not in page.text and 'Personal phone' not in page.text
    current = sharing.choices()[0]
    get_share_store().save_configuration(replace(cfg, persona=sharing.from_form(FormData([('persona_ids',current['id'])]))))
    refreshed = authenticated_client.post('/sharing/shares/'+grant.id+'/update', data={'csrf':make_csrf_token('frontend-test-user')})
    assert refreshed.status_code == 200
    assert 'A new achievement' in get_share_store().get_share(grant.id).snapshot.persona_entries[0].text


@pytest.mark.parametrize('width', [1440, 390])
def test_role_controls_keep_selections_and_render_markdown(editor_page, monkeypatch, width, tmp_path):
    from playwright.sync_api import expect
    from modules.hfl_shares import personalization
    rows = [dict(id=f'person-{i}', label=f'Person {i:02}', kind='people', color='#f97316', count=1) for i in range(65)]
    rows.append(dict(id='project-1', label='Testing project', kind='projects', color='#14b8a6', count=3))
    monkeypatch.setattr(personalization, 'entity_catalog', lambda: rows)
    from modules.hfl_corpus import workspace_views
    monkeypatch.setattr(workspace_views, 'listing', lambda: {'views':[{'id':'test-space', 'name':'Testing', 'color':'#14b8a6'}]})
    page, client = editor_page
    page.set_viewport_size({'width': width, 'height': 1100})
    page.goto('https://editing.test/roles')
    page.locator('#role-new').click()
    page.get_by_label('Facet name', exact=True).fill('UI patterns')
    page.get_by_role('button', name='Color #14b8a6', exact=True).click()
    page.get_by_label('Soul Markdown', exact=True).fill('## Experience\n**Testing** interfaces.')
    page.get_by_label('Facet name', exact=True).click()
    expect(page.locator('#role-markdown strong')).to_have_text('Testing')
    page.locator('#role-markdown').focus()
    page.keyboard.press('Enter')
    expect(page.get_by_label('Soul Markdown', exact=True)).to_be_focused()
    page.get_by_label('Soul Markdown', exact=True).fill('## Experience\n**Testing** interfaces. Updated.')
    page.locator('#role-space-picker summary').click()
    spaces = page.locator('#role-spaces input')
    assert spaces.count() > 0
    spaces.first.check()
    page.locator('#role-space-picker').press('Escape')
    assert not page.locator('#role-space-picker').evaluate('(e)=>e.open')
    expect(page.locator('#role-entity-status')).to_contain_text('65 matching entities; showing 50')
    expect(page.locator('#role-entities > button')).to_have_count(50)
    page.locator('#role-entities > button').first.click()
    page.locator('#role-entity-type').select_option('projects')
    expect(page.locator('#role-entities > button')).to_have_count(1)
    page.locator('#role-entities > button').first.click()
    page.locator('#role-entity-search').fill('no match')
    expect(page.locator('#role-entity-status')).to_have_text('0 matching entities.')
    expect(page.locator('#role-selected-entities > .role-selected-entity')).to_have_count(2)
    page.get_by_role('button', name='Save facet', exact=True).click()
    expect(page.locator('#role-status')).to_contain_text('Facet saved')
    expect(page.locator('#role-selected-entities')).to_contain_text('Testing project')
    expect(page.locator('#role-markdown')).to_contain_text('Updated.')
    saved = next(r for r in client.get('/roles/data').json()['roles'] if r['name']=='UI patterns')
    assert set(saved['entity_ids']) == {'person-0', 'project-1'}
    assert saved['workspace_ids'] and saved['color']=='#14b8a6'
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    editor = page.locator('#role-editor').bounding_box()
    sidebar = page.locator('.roles-layout > aside').bounding_box()
    if width == 1440:
        assert editor['x'] < sidebar['x']
        assert 1.9 < editor['width'] / sidebar['width'] < 2.2
    else:
        assert sidebar['y'] < editor['y']
    columns = page.locator('.role-context-row > div').all()
    a, b = [c.bounding_box() for c in columns]
    assert b['y'] > a['y']
    page.locator('#role-space-picker summary').click()
    page.screenshot(path=str(tmp_path / f'roles-controls-{width}.png'), full_page=True)
    page.locator('#role-clear-spaces').click()
    expect(page.locator('#role-spaces input:checked')).to_have_count(0)
    page.locator('#role-clear-entities').click()
    expect(page.locator('#role-selected-entities > .role-selected-entity')).to_have_count(0)


def test_role_upload_browser(editor_page):
    from playwright.sync_api import expect
    owner = role()
    page, client = editor_page
    page.goto('https://editing.test/roles')
    page.locator(f'[data-role="{owner["id"]}"]').click()
    page.locator('[data-pane=files]').click()
    expect(page.locator('#role-upload')).to_be_disabled()
    page.locator('#role-files').set_input_files({'name':'notes.txt','mimeType':'text/plain','buffer':b'Experience building reliable tools.'})
    expect(page.locator('#role-pending-files')).to_contain_text('notes.txt')
    page.get_by_role('button', name='Preview notes.txt', exact=True).click()
    expect(page.locator('#role-file-preview')).to_be_visible()
    expect(page.locator('#role-file-preview-content')).to_contain_text('Experience building reliable tools.')
    page.keyboard.press('Escape')
    expect(page.locator('#role-file-preview')).not_to_be_visible()
    expect(page.locator('#role-upload')).to_be_enabled()
    page.locator('#role-upload').click()
    expect(page.locator('#role-upload-status')).to_contain_text('Files processed',timeout=15000)
    expect(page.locator('[data-panel=files]')).to_be_visible()
    expect(page.locator('#role-file-list')).to_contain_text('notes.txt')
    expect(page.locator('#role-upload')).to_be_disabled()
    assert store.get(owner['id'])['files'][0]['text']=='Experience building reliable tools.'


@pytest.mark.parametrize('width', [1440, 390])
def test_personal_context_is_agent_evidence_without_about_module(editor_page, width):
    from playwright.sync_api import expect
    from test_share_guest_views import make_share
    from modules.hfl_shares.agent import _context
    role()
    selected = sharing.from_form(FormData([('persona_ids', sharing.choices()[0]['id'])]))
    snapshot = build_snapshot(config(selected), ())
    assert 'Built test tools' in _context(snapshot, entries=snapshot.persona_entries)
    assert 'Personal phone' not in _context(snapshot, entries=snapshot.persona_entries)
    grant = make_share(snapshot)
    page, client = editor_page
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto('https://editing.test/sharing/shares/' + grant.id + '/preview')
    page.locator('[data-preview-toast-close]').click()
    expect(page.locator('[data-share-view=about]')).to_have_count(0)
    expect(page.locator('[data-share-main=about]')).to_have_count(0)
    expect(page.get_by_text('Built test tools.', exact=True)).to_have_count(0)
    expect(page.locator('[data-personal-citation-dialog]')).to_have_count(0)
    from modules.hfl_shares.router import _answer_html, _citation_pages
    citation = snapshot.persona_entries[0].citation
    answer = str(_answer_html(f'Experience: [[Built test tools|{citation}]]. [{citation}]', _citation_pages(grant)))
    assert 'Built test tools' in answer
    assert 'href=' not in answer
    assert 'See entry' not in answer
