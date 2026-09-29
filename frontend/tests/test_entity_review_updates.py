"""Custom entity vocabulary and reviewed batch merges use current, isolated data."""
import json
from pathlib import Path
from uuid import uuid4

import pytest

from modules.hfl_corpus import entities
from workflows.hfl import entity_matching, entity_merges, entity_types
from workflows.hfl.entity_store import get_store


@pytest.fixture
def review_data(monkeypatch):
    monkeypatch.setattr(entities, 'current_entries', lambda: [])
    monkeypatch.setattr(entity_merges, 'flush_audits', lambda: None)
    monkeypatch.setattr(entity_matching, 'dispatch_pending', lambda: None)
    monkeypatch.setenv('HARQIS_ENTITY_AUTO_MATCH', '1')
    for identity, kind, name in [('a','people','Alex A'), ('b','people','Alex B'),
                                 ('c','people','Alex C'), ('p','pets','Fido'), ('q','pets','Fido puppy')]:
        get_store().save_profile(identity, kind, dict(name=name, categories=['Home'], emails=[], phones=[], references=[], notes='Original '+identity))
    with get_store().connection() as db:
        db.execute("INSERT INTO entity_match_jobs(id,mode,seeds,state) VALUES ('test','history','[]','running')")
        for identity, left, right in [('ab','a','b'), ('bc','b','c'), ('pq','p','q')]:
            data = dict(entity_ids=[left,right], names=[left,right], decision={'reason':'Review shared identity', 'facts':[]})
            db.execute("INSERT INTO entity_match_pairs(id,job_id,left_id,right_id,state,data) VALUES (?,'test',?,?,'suggested',?)", (identity,left,right,json.dumps(data)))


def payload(client, ids, name):
    body = dict(entity_ids=ids, name=name)
    response = client.post('/api/hfl/entities/merge-preview', json=body)
    assert response.status_code == 200, response.text
    return {**body, 'preview_token':response.json()['preview_token'], 'request_id':str(uuid4())}


def test_custom_types_manual_creation_and_reclassification(review_data, authenticated_client):
    client = authenticated_client
    spec = dict(name='Farm animals', color='#aabbcc', description='Named farm animals, excluding pets.')
    assert client.post('/api/hfl/entities/types', json=spec).status_code == 200
    assert client.post('/api/hfl/entities/types', json=spec).status_code == 409
    assert client.post('/api/hfl/entities/types', json={**spec,'name':'Organizations'}).status_code == 409
    created = client.post('/api/hfl/entities/create', json=dict(name='Bessie', kind='farm-animals')).json()['id']
    assert client.post('/api/hfl/entities/type/'+created, json={'kind':'pets'}).status_code == 200
    data = client.get('/api/hfl/entities').json()
    assert next(e for e in data['entities'] if e['id']==created)['kind'] == 'pets'
    assert any(t['id']=='farm-animals' for t in data['types'])
    assert client.post('/api/hfl/entities/type/'+created, json={'kind':'unknown'}).status_code == 400
    assert entities.mention({'id':'one'},'pets','Fido','Fido','test')['id'] != entities.mention({'id':'two'},'pets','Fido','Fido','test')['id']


def test_type_backfill_is_explicit_and_preserves_existing_projection(review_data, authenticated_client, monkeypatch):
    from workflows.hfl import entity_events
    row = dict(id='entry',title='Pet',text='Fido is my pet.',source='notes',date='2026-09-01',tags=[],path='day.md',anchor='',ref='')
    monkeypatch.setattr(entities,'current_entries',lambda:[row])
    get_store().save('entry',entities.entry_hash(row),[entities.mention(row,'topics','Fido','Fido','test')])
    monkeypatch.setattr(entities,'extract_batch',lambda rows:{e['id']:[entities.mention(e,'pets','Fido','Fido','model-extracted')] for e in rows})
    monkeypatch.setattr(entity_events,'request_enrichment',lambda:{'state':'queued'})
    entity_types.create('Birds','#aabbcc','Named birds')
    assert entities.enrich()['processed']==0
    assert authenticated_client.post('/api/hfl/entities/backfill?include_new_types=true').status_code==200
    assert entities.projection()[0]['mentions'][0]['kind']=='topics'
    assert entities.enrich()['processed']==1
    assert entities.enrich()['processed']==0
    assert entities.projection()[0]['mentions'][0]['kind']=='pets'


def test_batch_disjoint_merges_survive_unrelated_changes_and_retry(review_data, authenticated_client):
    client=authenticated_client
    groups=[payload(client,['a','b','c'],'Alex'),payload(client,['p','q'],'Fido')]
    get_store().save_profile('unrelated','tools',dict(name='Tool',categories=[],emails=[],phones=[],references=[],notes=''))
    first=client.post('/api/hfl/entities/merges/batch',json={'groups':groups})
    assert first.status_code==200
    assert all('result' in r for r in first.json()['results'])
    assert client.post('/api/hfl/entities/merges/batch',json={'groups':groups}).json()==first.json()
    assert client.get('/api/hfl/entities/matching?all=true').json()['suggestions_total']==0


def test_batch_partial_failure_preserves_other_groups(review_data, authenticated_client):
    client=authenticated_client
    groups=[payload(client,['a','b'],'Alex'),payload(client,['p','q'],'Fido')]
    get_store().save_profile('a','people',dict(name='Changed',categories=[],emails=[],phones=[],references=[],notes=''))
    result=client.post('/api/hfl/entities/merges/batch',json={'groups':groups}).json()['results']
    assert 'error' in result[0] and 'result' in result[1]
    assert get_store().resolve('a')=='a'


def test_batch_rejects_overlap_and_cross_type(review_data, authenticated_client):
    client=authenticated_client
    groups=[payload(client,['a','b'],'Alex'),payload(client,['b','c'],'Alex')]
    assert client.post('/api/hfl/entities/merges/batch',json={'groups':groups}).status_code==400
    assert client.post('/api/hfl/entities/merge-preview',json=dict(entity_ids=['a','p'],name='Invalid')).status_code==409


def test_suggestions_resolve_aliases_and_pending_jobs_share_pairs(review_data, authenticated_client):
    client=authenticated_client
    body=payload(client,['a','b'],'Alex')
    merged=client.post('/api/hfl/entities/merges',json=body).json()['entity_id']
    data=client.get('/api/hfl/entities/matching?all=true').json()
    suggestion=next(s for s in data['suggestions'] if s['id']=='bc')
    assert suggestion['data']['entity_ids']==[merged,'c']
    assert merged in {e['id'] for e in data['entities']}
    job=entity_matching.request_scan(seeds=['p'])['id']
    entity_matching.prepare(job,entities.entity_index())
    with get_store().connection() as db:
        assert db.execute("SELECT count(*) FROM entity_match_pairs WHERE left_id='p' AND right_id='q' AND state IN ('pending','suggested')").fetchone()[0]==1


def test_full_suggestions_endpoint_covers_more_than_first_hundred(review_data, authenticated_client):
    with get_store().connection() as db:
        for i in range(110):
            data=json.dumps(dict(entity_ids=[f'x{i}',f'y{i}'],names=['X','Y']))
            db.execute("INSERT INTO entity_match_pairs(id,job_id,left_id,right_id,state,data) VALUES (?,'test',?,?,'suggested',?)",(str(i),f'x{i}',f'y{i}',data))
    assert len(authenticated_client.get('/api/hfl/entities/matching').json()['suggestions'])==100
    assert len(authenticated_client.get('/api/hfl/entities/matching?all=true').json()['suggestions'])==113


@pytest.mark.parametrize('operation', ['merge', 'dismiss', 'dismiss-retry'])
def test_review_browser_preserves_poll_state_filters_and_batches(review_data, authenticated_client, tmp_path, operation):
    import re
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as engine:
        options={'headless':True}
        if not Path(engine.chromium.executable_path).exists():
            if Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe').exists():
                options['channel']='msedge'
            else:
                pytest.skip('Install Playwright Chromium')
        browser=engine.chromium.launch(**options)
        try:
            page=browser.new_page(viewport={'width':1100,'height':1000})
            page.clock.install()
            errors=[]
            matching_requests=[]
            dismiss_requests=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            def route_request(route):
                req=route.request
                if '/matching/suggestions/' in req.url and req.url.endswith('/dismiss'):
                    assert page.locator('#suggestions-progress').is_visible()
                    assert page.locator('#suggestions-progress').get_attribute('value') is not None
                    dismiss_requests.append(req.url)
                    if operation == 'dismiss-retry' and req.url.endswith('/bc/dismiss') and dismiss_requests.count(req.url) == 1:
                        route.fulfill(status=503, content_type='application/json', body='{"detail":"Temporary failure"}')
                        return
                if req.url.endswith('/merges/batch'):
                    assert page.locator('#batch-progress').is_visible()
                    assert page.locator('#batch-progress').get_attribute('value') is None
                if '/matching?' in req.url: matching_requests.append(req.url)
                response=authenticated_client.request(req.method,req.url.replace('https://entities.test',''),content=req.post_data_buffer,headers={'content-type':req.headers.get('content-type','application/json')})
                route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-encoding','content-length'}})
            page.route('https://entities.test/**',route_request)
            page.goto('https://entities.test/hfl-corpus/entities')
            page.wait_for_selector('.matching-suggestion',state='attached')
            page.locator('#matching-panel > summary').click()
            assert page.locator('#suggestions-dismiss').is_disabled()
            page.locator('#matching-status details > summary').click()
            first=page.locator('.matching-suggestion').first
            first.locator('summary').click()
            first.locator('input').check()
            for _ in range(3):
                page.clock.run_for(11000)
                assert first.get_attribute('open') is not None
                assert first.locator('input').is_checked()
                assert page.locator('#matching-status details').get_attribute('open') is not None
            assert len(matching_requests)>=4
            page.click('#suggestions-clear')
            page.locator('#filter-kind').get_by_role('button',name=re.compile('^Pets')).click()
            assert page.locator('.matching-suggestion').count()==1
            assert page.locator('.matching-suggestion .entity-kind').inner_text()=='Pets'
            page.click('#suggestions-select')
            page.locator('#filter-kind').get_by_role('button',name=re.compile('^Pets')).click()
            page.locator('#filter-kind').get_by_role('button',name=re.compile('^People')).click()
            assert '1 hidden' in page.locator('#suggestions-selection').inner_text()
            page.click('#suggestions-select')
            if operation.startswith('dismiss'):
                page.set_viewport_size({'width':390,'height':844})
                page.click('#suggestions-dismiss')
                playwright.expect(page.locator('#suggestions-feedback')).to_contain_text('suggestions kept separate.')
                if operation == 'dismiss-retry':
                    playwright.expect(page.locator('#suggestions-feedback')).to_contain_text('1 failed and remain selected')
                    playwright.expect(page.locator('#suggestions-selection')).to_have_text('1 selected')
                    assert {s['id'] for s in entity_matching.status()['suggestions']} == {'bc'}
                    page.click('#suggestions-dismiss')
                    playwright.expect(page.locator('#suggestions-feedback')).to_have_text('1 suggestions kept separate.')
                else:
                    playwright.expect(page.locator('#suggestions-feedback')).to_have_text('3 suggestions kept separate.')
                playwright.expect(page.locator('#suggestions-dismiss')).to_be_disabled()
                playwright.expect(page.locator('#suggestions-progress')).to_be_hidden()
                assert entity_matching.status()['suggestions_total'] == 0
                assert len(entities.entity_index()) == 5
                assert any(url.endswith('/pq/dismiss') for url in dismiss_requests)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert not errors
                return
            page.click('#suggestions-submit')
            page.wait_for_selector('#batch-confirm:not([disabled])')
            playwright.expect(page.locator('#batch-progress')).to_be_hidden()
            assert page.locator('.batch-group').count()==2
            assert len(entities.entity_index())==5
            page.screenshot(path=str(tmp_path / 'batch-desktop.png'))
            page.set_viewport_size({'width':390,'height':844})
            assert page.locator('#batch-merge-dialog').evaluate('(el) => el.scrollWidth <= el.clientWidth')
            page.screenshot(path=str(tmp_path / 'batch-mobile.png'))
            page.locator('[data-batch-field=name]').first.fill('Reviewed group')
            page.click('#batch-confirm')
            page.wait_for_selector('#batch-merge-dialog:not([open])',state='attached')
            assert len(entities.entity_index())==2
            assert any(e['label']=='Reviewed group' for e in entities.entity_index())
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not errors
        finally:
            browser.close()


def test_type_and_batch_endpoints_require_owner(review_data, authenticated_client):
    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as anonymous:
        for path, body in [('/types', dict(name='Birds',color='#aabbcc',description='Named birds')),
                           ('/create',dict(name='Fido',kind='pets')),('/type/a',{'kind':'pets'}),
                           ('/merges/batch',{'groups':[payload(authenticated_client,['a','b'],'Alex')]}),
                           ('/backfill?include_new_types=true',{})]:
            assert anonymous.post('/api/hfl/entities'+path,json=body).status_code==401


def test_extraction_uses_custom_vocabulary_and_rejects_unknown_types(review_data, monkeypatch):
    from types import SimpleNamespace
    from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
    import apps.antropic.config as config
    entity_types.create('Birds','#aabbcc','Named birds')
    row=dict(id='bird-entry',text='Polly is a bird. Fido is a pet.',tags=[])
    captured=[]
    def send(self, **kwargs):
        captured.append(kwargs['system'])
        mentions=[dict(kind=kind,name=name,evidence=evidence) for kind,name,evidence in
                  [('birds','Polly','Polly is a bird.'),('pets','Fido','Fido is a pet.'),('unknown','Polly','Polly is a bird.')]]
        return SimpleNamespace(content=[SimpleNamespace(text=json.dumps({'entries':[{'id':row['id'],'mentions':mentions}]}))])
    monkeypatch.setattr(config,'get_config',lambda name: {})
    monkeypatch.setattr(BaseApiServiceAnthropic,'__init__',lambda self, config: None)
    monkeypatch.setattr(BaseApiServiceAnthropic,'send_messages',send)
    result=entities.extract_batch([row])
    assert {m['kind'] for m in result[row['id']]}=={'birds','pets'}
    assert 'Named birds' in captured[0]


def test_dismiss_resolved_group_blocks_all_members_and_duplicate_suggestions(review_data, authenticated_client):
    client=authenticated_client
    client.post('/api/hfl/entities/merges',json=payload(client,['a','b'],'Alex'))
    with get_store().connection() as db:
        original=db.execute("SELECT * FROM entity_match_pairs WHERE id='bc'").fetchone()
        db.execute("INSERT INTO entity_match_pairs(id,job_id,left_id,right_id,state,data) VALUES ('duplicate','test','b','c','suggested',?)",(original['data'],))
    assert client.post('/api/hfl/entities/matching/suggestions/bc/dismiss').status_code==200
    assert {s['id'] for s in entity_matching.status()['suggestions']}=={'pq'}
    with get_store().connection() as db:
        assert entity_matching.blocked(db,['a','c'])
        assert entity_matching.blocked(db,['b','c'])
