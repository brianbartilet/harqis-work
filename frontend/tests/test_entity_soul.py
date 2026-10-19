"""Soul knowledge, scoped resolution, reversals and editor use isolated stores."""
import json
from pathlib import Path
from uuid import uuid4

import pytest

from modules.hfl_corpus import entities
from workflows.hfl import entity_resolution as resolution, entity_soul, entity_matching, entity_merges
from workflows.hfl.entity_store import get_store


@pytest.fixture
def soul_data(monkeypatch):
    monkeypatch.setenv('HARQIS_ENTITY_AUTO_MATCH', '1')
    rows = [dict(id='entry-one', title='Work log', text='Brian finished the migration.', source='notes',
                 date='2026-10-19', tags=[], path='day.md', anchor='', ref='')]
    monkeypatch.setattr(entities, 'current_entries', lambda: list(rows))
    monkeypatch.setattr(resolution, 'dispatch_pending', lambda: None)
    monkeypatch.setattr(entity_matching, 'dispatch_pending', lambda: None)
    monkeypatch.setattr(entity_merges, 'flush_audits', lambda: None)
    for identity, name, kind in [('brian', 'Brian Bartilet', 'people'), ('company', 'Acme', 'companies')]:
        get_store().save_profile(identity, kind, dict(name=name, aliases=['Brian'] if identity == 'brian' else [], categories=[], emails=[], phones=[], references=[], notes=''))
    mention = entities.mention(rows[0], 'people', 'Brian', rows[0]['text'], 'model-extracted')
    get_store().save(rows[0]['id'], entities.entry_hash(rows[0]), [mention], match=True)
    return rows, mention


def soul_payload(**changes):
    return dict(version=0, markdown='Brian owns this corpus.', identity_rules=[dict(
        id='rule', observed_name='Brian', sources=['notes'], required_context=[], excluded_context=[], enabled=True)],
        relationships=[], journal=[], **changes)


def save(client, payload=None, identity='brian'):
    response = client.post('/api/hfl/entities/soul/' + identity, json=payload or soul_payload())
    assert response.status_code == 200, response.text
    return response.json()['soul']


def test_soul_context_provenance_version_and_safe_markdown(soul_data, authenticated_client):
    payload = soul_payload()
    payload.update(markdown='# Brian\n<script>alert(1)</script>',
                   relationships=[dict(id='rel', target_id='company', relation='works_at', since='2026-01-01', evidence='Owner confirmed')],
                   journal=[dict(id='note', text='Corrected the name.')])
    saved = save(authenticated_client, payload)
    assert saved['version'] == 1
    assert saved['identity_rules'][0]['provenance']['basis'] == 'user-confirmed'
    context = authenticated_client.get('/api/hfl/entities/context/brian').json()
    assert '<script>' not in context['soul_html'] and '<h1' in context['soul_html']
    assert context['soul']['relationships'][0]['target_name'] == 'Acme'
    assert authenticated_client.post('/api/hfl/entities/soul/brian', json=payload).status_code == 409
    payload['version'] = 1
    again = save(authenticated_client, payload)
    assert again['identity_rules'][0]['provenance'] == saved['identity_rules'][0]['provenance']
    assert entity_merges.history('brian')[-1]['action'] == 'soul-edited'


@pytest.mark.parametrize('case', ['scope', 'context', 'excluded', 'surname', 'competing', 'disabled', 'type'])
def test_rules_require_unambiguous_scope(soul_data, authenticated_client, case):
    rows, mention = soul_data
    payload = soul_payload()
    if case == 'scope': payload['identity_rules'][0]['sources'] = ['calendar']
    if case == 'context': payload['identity_rules'][0]['required_context'] = ['specific project']
    if case == 'excluded': payload['identity_rules'][0]['excluded_context'] = ['migration']
    if case == 'disabled': payload['identity_rules'][0]['enabled'] = False
    if case == 'surname':
        rows[0]['text'] = 'Brian Smith finished the migration.'
        get_store().save(rows[0]['id'], entities.entry_hash(rows[0]), [mention], match=True)
    if case == 'type':
        get_store().save_profile('brian', 'companies', dict(name='Brian Bartilet', categories=[], notes=''))
    save(authenticated_client, payload)
    if case == 'competing':
        get_store().save_profile('other', 'people', dict(name='Brian Jones', categories=[], notes=''))
        save(authenticated_client, identity='other')
    resolution.process_batch(use_model=False)
    assert entities.projection()[0]['mentions'][0]['id'] == mention['id']


def test_rule_assignment_undo_and_source_edits(soul_data, authenticated_client):
    rows, mention = soul_data
    save(authenticated_client)
    get_store().state('entity-consolidation-owner', 'hermes')
    resolution.process_batch(use_model=False)
    assert entities.projection()[0]['mentions'][0]['id'] == 'brian'
    with get_store().connection() as db:
        assert db.execute('SELECT count(*) FROM entity_merges').fetchone()[0] == 0
    rows[0]['text'] += ' Updated.'
    assert not entities.projection()[0]['mentions']  # stale extraction is suppressed
    rows[0]['text'] = 'Brian finished the migration.'
    result = authenticated_client.post(f"/api/hfl/entities/resolutions/{rows[0]['id']}/{mention['id']}/undo", json={})
    assert result.status_code == 200
    assert entities.projection()[0]['mentions'][0]['id'] == mention['id']
    get_store().save(rows[0]['id'], entities.entry_hash(rows[0]), [mention], match=True)
    resolution.process_batch(use_model=False)
    assert entities.projection()[0]['mentions'][0]['id'] == mention['id']


def test_rule_revocation_immediately_invalidates_assignment(soul_data, authenticated_client):
    save(authenticated_client)
    resolution.process_batch(use_model=False)
    assert entities.projection()[0]['mentions'][0]['id'] == 'brian'
    payload = soul_payload(); payload.update(version=1, identity_rules=[])
    save(authenticated_client, payload)
    assert entities.projection()[0]['mentions'][0]['id'] == soul_data[1]['id']


def test_soul_survives_profile_edit_merge_and_undo(soul_data, authenticated_client):
    save(authenticated_client)
    client = authenticated_client
    assert client.post('/api/hfl/entities/profile/brian', json={'name':'Brian Bartilet', 'notes':'Edited'}).status_code == 200
    assert entity_soul.all_souls()['brian']['markdown']
    body = dict(entity_ids=['brian', soul_data[1]['id']], name='Brian Bartilet')
    preview = client.post('/api/hfl/entities/merge-preview', json=body).json()
    merged = client.post('/api/hfl/entities/merges', json={**body, 'request_id':str(uuid4()), 'preview_token':preview['preview_token']})
    assert merged.status_code == 200, merged.text
    identity = merged.json()['entity_id']
    assert entity_soul.all_souls()[identity]['identity_rules']
    assert client.post('/api/hfl/entities/merges/'+identity+'/unmerge', json={'request_id':str(uuid4())}).status_code == 200
    assert entity_soul.all_souls()['brian']['identity_rules'][0]['id'] == 'rule'


def test_relationship_edges_require_visible_endpoints(soul_data, authenticated_client):
    rows, mention = soul_data
    payload = soul_payload()
    payload['relationships'] = [dict(id='rel', target_id='company', relation='works_at', evidence='Owner confirmed')]
    save(authenticated_client, payload)
    resolution.process_batch(use_model=False)
    assert not any(e['relation'] == 'works_at' for e in entities._corpus_graph()['edges'])
    company_entry = {**rows[0], 'id':'company-entry', 'text':'Acme', 'source':'calendar'}
    rows.append(company_entry)
    get_store().save(company_entry['id'], entities.entry_hash(company_entry),
                     [dict(id='company', kind='companies', label='Acme', evidence='Acme', method='test', resolution='curated')])
    assert any(e['relation'] == 'works_at' and e['method'] == 'user-confirmed' for e in entities._corpus_graph()['edges'])
    assert not any(e['relation'] == 'works_at' for e in entities._corpus_graph(source='notes')['edges'])


def test_disabled_resolution_keeps_intent(soul_data, monkeypatch):
    monkeypatch.setenv('HARQIS_ENTITY_AUTO_MATCH', '0')
    assert resolution.process_batch()['state'] == 'disabled'
    assert resolution.status()['pending'] == 1


def test_soul_endpoints_require_owner_authentication():
    from fastapi.testclient import TestClient
    from hfl_api import app
    client = TestClient(app)
    assert client.get('/api/hfl/entities/context/brian').status_code == 401
    assert client.post('/api/hfl/entities/soul/brian', json=soul_payload()).status_code == 401
    assert client.post('/api/hfl/entities/resolutions/entry/mention/undo', json={}).status_code == 401


def test_prose_does_not_authorize_and_jobs_survive_model_error(soul_data, authenticated_client, monkeypatch):
    payload = soul_payload(); payload['identity_rules'] = []
    save(authenticated_client, payload)
    resolution.process_batch(use_model=False)
    assert entities.projection()[0]['mentions'][0]['id'] == soul_data[1]['id']
    rows, mention = soul_data
    get_store().save(rows[0]['id'], entities.entry_hash(rows[0]), [mention], match=True)
    monkeypatch.setattr(entity_matching, 'evaluate', lambda pairs, **kwargs: (_ for _ in ()).throw(RuntimeError('provider offline')))
    with pytest.raises(RuntimeError): resolution.process_batch()
    with get_store().connection() as db:
        assert db.execute('SELECT count(*) FROM entity_resolution_jobs').fetchone()[0] == 1


def test_schema_rejects_unscoped_rules_invalid_dates_and_forged_provenance(soul_data, authenticated_client):
    client = authenticated_client
    for sources in [[], ['*'], [' ']]:
        payload = soul_payload(); payload['identity_rules'][0]['sources'] = sources
        assert client.post('/api/hfl/entities/soul/brian', json=payload).status_code == 422
    payload = soul_payload(); payload['identity_rules'][0]['provenance'] = {'actor':'someone else'}
    assert client.post('/api/hfl/entities/soul/brian', json=payload).status_code == 422
    payload = soul_payload(); payload['relationships'] = [dict(target_id='company', relation='works_at', since='2026-02-31')]
    assert client.post('/api/hfl/entities/soul/brian', json=payload).status_code == 422


def test_contextual_assignment_requires_literal_evidence_and_rechecks_changes(soul_data, monkeypatch):
    rows, mention = soul_data
    fact = 'Brian led the Mercury migration with Priya in Singapore during March 2025.'
    rows[0]['text'] = fact
    mention['evidence'] = fact
    known = {**rows[0], 'id':'known', 'source':'calendar'}
    rows.append(known)
    get_store().save('known', entities.entry_hash(known), [{**mention, 'id':'brian'}])
    get_store().save(rows[0]['id'], entities.entry_hash(rows[0]), [mention], match=True)
    def evaluate(pairs, **kwargs):
        return ([dict(id=p['id'], decision='merge', reason='Same specific event and participants', contradictions=[],
                      facts=[dict(left_quote=fact, right_quote=fact, explanation='Mercury migration with Priya')]) for p in pairs], 'test-model')
    monkeypatch.setattr(entity_matching, 'evaluate', evaluate)
    resolution.process_batch()
    assert entities.projection()[0]['mentions'][0]['id'] == 'brian'
    known['text'] = 'The event details were corrected.'
    assert entities.projection()[0]['mentions'][0]['id'] == mention['id']


@pytest.mark.parametrize('case', ['invented', 'contradiction', 'competitor', 'stale'])
def test_contextual_resolution_rejects_unsupported_or_changed_evidence(soul_data, monkeypatch, case):
    rows, mention = soul_data
    fact = 'Brian led the Mercury migration with Priya in Singapore during March 2025.'
    rows[0]['text'] = fact
    mention['evidence'] = fact
    rows.append({**rows[0], 'id':'known', 'source':'calendar'})
    get_store().save('known', entities.entry_hash(rows[1]), [{**mention, 'id':'brian'}])
    get_store().save(rows[0]['id'], entities.entry_hash(rows[0]), [mention], match=True)
    if case == 'competitor':
        get_store().save_profile('other', 'people', dict(name='Brian Another', aliases=['Brian'], categories=[], notes=''))
    def evaluate(pairs, **kwargs):
        if case == 'stale':
            get_store().save_profile('brian', 'people', dict(name='Changed', categories=[], notes=''))
        return ([dict(id=p['id'], decision='review' if p['right']['id'] == 'other' else 'merge',
                      reason='Candidate review', contradictions=['different person'] if case == 'contradiction' else [],
                      facts=[dict(left_quote='Invented identification not present in any original entry.' if case == 'invented' else fact,
                                  right_quote=fact, explanation='Specific event')]) for p in pairs], 'test-model')
    monkeypatch.setattr(entity_matching, 'evaluate', evaluate)
    if case == 'stale':
        with pytest.raises(ValueError, match='state changed'): resolution.process_batch()
    else:
        resolution.process_batch()
    assert entities.projection()[0]['mentions'][0]['id'] == mention['id']


@pytest.mark.parametrize('width', [1440, 390])
def test_soul_editor_browser(soul_data, authenticated_client, tmp_path, width):
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as engine:
        options = {'headless': True}
        if not Path(engine.chromium.executable_path).exists():
            options['channel'] = 'msedge'
        browser = engine.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={'width':width, 'height':1000})
            errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
            def route_request(route):
                req = route.request
                response = authenticated_client.request(req.method, req.url.replace('https://entities.test',''),
                    content=req.post_data_buffer, headers={'content-type':req.headers.get('content-type','application/json')})
                route.fulfill(status=response.status_code, body=response.content,
                    headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-encoding','content-length'}})
            page.route('https://entities.test/**', route_request)
            page.goto('https://entities.test/hfl-corpus/entities')
            card = page.locator('[data-entity-id="brian"]')
            card.locator(':scope > summary').click()
            card.get_by_text('Soul, identity and relationships', exact=True).click()
            card.get_by_label('Soul (Markdown)').fill('# Brian Bartilet\nCorpus owner.')
            card.get_by_role('button', name='Add identity rule', exact=True).click()
            card.get_by_label('Observed name', exact=True).fill('Brian')
            card.get_by_label('Activity sources (one per line)').fill('notes')
            card.get_by_role('button', name='Add relationship', exact=True).click()
            card.get_by_label('Find entity by name').fill('Acme')
            card.get_by_role('button', name='Acme · companies').click()
            card.get_by_role('button', name='Add journal note', exact=True).click()
            card.get_by_label('Note', exact=True).fill('Confirmed my identity.')
            card.get_by_role('button', name='Save soul', exact=True).click()
            page.wait_for_function("!document.querySelector('#entity-loading') || document.querySelector('#entity-loading').hidden")
            playwright.expect(card.locator('.entity-soul')).not_to_have_attribute('open','')
            card.get_by_text('Soul, identity and relationships', exact=True).click()
            playwright.expect(card.get_by_label('Soul (Markdown)')).to_have_value('# Brian Bartilet\nCorpus owner.')
            playwright.expect(card.get_by_label('Observed name', exact=True)).to_have_value('Brian')
            playwright.expect(card.get_by_label('Find entity by name')).to_have_value('Acme')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(tmp_path / f'soul-{width}.png'), full_page=True)
            for section, label in [('identity', 'Observed name'), ('relationships', 'Find entity by name'), ('journal', 'Note')]:
                card.get_by_label(label, exact=True).scroll_into_view_if_needed()
                assert card.locator('.entity-soul').evaluate('(node) => node.scrollWidth <= node.clientWidth')
                page.screenshot(path=str(tmp_path / f'soul-{section}-{width}.png'))
            assert not errors
        finally:
            browser.close()
