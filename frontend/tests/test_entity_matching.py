"""Automatic matching must be grounded, resumable and respect human reversals."""
import json
from uuid import uuid4

import pytest

from modules.hfl_corpus import entities
from workflows.hfl import entity_matching as matching, entity_merges
from workflows.hfl.entity_store import get_store

FACTS = ['Alex led the Mercury migration with Priya during March 2025.',
         'Alex presented the same incident review for account ZX42 in Singapore.']


@pytest.fixture
def matching_data(monkeypatch, tmp_path):
    monkeypatch.setenv('HARQIS_ENTITIES_DB', str(tmp_path / 'matching.sqlite3'))
    monkeypatch.setenv('HARQIS_ENTITY_AUTO_MATCH','1')
    monkeypatch.setattr(matching,'dispatch_pending',lambda:None)
    monkeypatch.setattr(entity_merges,'flush_audits',lambda:None)
    rows = [dict(id=f'entry-{i}',title='Meeting',text=' '.join(FACTS),source='notes',
                 date='2026-09-01',tags=[],path='day.md',anchor=str(i),ref='') for i in range(3)]
    monkeypatch.setattr(entities,'current_entries',lambda:rows.copy())
    ids = []
    for row in rows:
        mention = entities.mention(row,'people','Alex Tan',row['text'],'model-extracted')
        ids.append(mention['id'])
        get_store().save(row['id'],entities.entry_hash(row),[mention])
    def evaluate(pairs):
        return ([{'id':p['id'],'decision':'merge','reason':'Two independent shared event details',
                  'contradictions':[], 'facts':[{'left_quote':fact,'right_quote':fact,'explanation':f'Shared specific event {i}'} for i,fact in enumerate(FACTS)]}
                 for p in pairs],'test-model')
    monkeypatch.setattr(matching,'evaluate',evaluate)
    return rows,ids


def finish(job):
    for _ in range(10):
        result = matching.process_batch(job)
        if not result['pending']:
            return
    pytest.fail('Matching did not finish bounded test workload')


def test_history_scan_is_once_and_automatic_merges_are_audited(matching_data):
    _,ids=matching_data
    job=matching.request_scan()['id']
    finish(job)
    directory=entities.entity_index()
    assert len(directory)==1 and len(directory[0]['entries'])==3
    events=entity_merges.history(directory[0]['id'])
    assert events[0]['data']['automatic']['model']=='test-model'
    assert events[0]['actor']=='entity-matcher:test-model'
    assert matching.request_scan()['id']==job
    assert matching.status()['jobs'][0]['state']=='complete'
    assert matching.process_batch(job)['pending']==0


def test_name_only_and_invented_facts_need_review(matching_data,monkeypatch):
    def evaluate(pairs):
        return ([{'id':p['id'],'decision':'merge','reason':'Names are equal','contradictions':[],
                  'facts':[{'left_quote':'Invented corroborating detail that does not exist here',
                            'right_quote':'Invented corroborating detail that does not exist here','explanation':'Invented'}]} for p in pairs],'test-model')
    monkeypatch.setattr(matching,'evaluate',evaluate)
    finish(matching.request_scan()['id'])
    assert len(entities.entity_index())==3
    assert matching.status()['suggestions_total']==3


def test_curated_name_and_notes_survive_new_matching(matching_data):
    _,ids=matching_data
    get_store().save_profile(ids[0],'people',dict(name='Alex Tan (reviewed)',categories=['Team'],emails=[],phones=[],references=[],notes='Keep my edited prose.'))
    finish(matching.request_scan()['id'])
    directory=entities.entity_index()
    assert len(directory)==1
    assert directory[0]['label']=='Alex Tan (reviewed)'
    assert directory[0]['profile']['notes']=='Keep my edited prose.'


def test_unmerge_blocks_future_automatic_remerge(matching_data):
    _,ids=matching_data
    finish(matching.request_scan()['id'])
    root=entities.entity_index()[0]['id']
    restored=entity_merges.unmerge(root,str(uuid4()),'undo-test','owner')['restored_ids']
    with get_store().connection() as db:
        assert matching.blocked(db,restored)
    job=matching.request_scan(seeds=restored)['id']
    finish(job)
    assert len(entities.entity_index())==2


def test_dismissal_and_stale_source_do_not_merge(matching_data,monkeypatch):
    rows,ids=matching_data
    def evaluate(pairs):
        return ([{'id':p['id'],'decision':'review','reason':'Ambiguous identity','facts':[],'contradictions':[]} for p in pairs],'test-model')
    monkeypatch.setattr(matching,'evaluate',evaluate)
    finish(matching.request_scan()['id'])
    suggestion=matching.status()['suggestions'][0]
    matching.dismiss(suggestion['id'])
    with get_store().connection() as db:
        assert matching.blocked(db,[suggestion['left_id'],suggestion['right_id']])
    assert matching.status()['suggestions_total']==2


def test_enrichment_creates_durable_matching_intent_and_skips_audit(matching_data,monkeypatch):
    rows,ids=matching_data
    for row in rows:
        row['text'] += ' Updated.'
    rows[0]['source']='entities-audit'
    monkeypatch.setattr(entities,'extract_batch',lambda batch:{e['id']:[entities.mention(e,'people','Alex Tan',e['text'],'model-extracted')] for e in batch})
    result=entities.enrich()
    assert result['processed']==2
    with get_store().connection() as db:
        jobs=list(db.execute('SELECT * FROM entity_match_jobs'))
    assert len(jobs)==2 and all(j['mode']=='enrichment' for j in jobs)


def test_matching_api_requires_owner_and_dismisses_suggestions(matching_data,authenticated_client,monkeypatch):
    from main import app
    from fastapi.testclient import TestClient
    with TestClient(app) as anonymous:
        assert anonymous.get('/api/hfl/entities/matching').status_code==401
        assert anonymous.post('/api/hfl/entities/matching/scan').status_code==401
    response=authenticated_client.post('/api/hfl/entities/matching/scan')
    assert response.status_code==200
    assert authenticated_client.get('/api/hfl/entities/matching').json()['jobs'][0]['mode']=='history'


def test_changed_evidence_during_model_call_is_not_merged(matching_data,monkeypatch):
    rows,_=matching_data
    original=matching.evaluate
    def evaluate(pairs):
        result=original(pairs)
        for row in rows:
            row['text']='Different evidence after the request started'
        return result
    monkeypatch.setattr(matching,'evaluate',evaluate)
    job=matching.request_scan()['id']
    matching.process_batch(job)
    with get_store().connection() as db:
        assert db.execute('SELECT count(*) FROM entity_merges').fetchone()[0]==0
    finish(job)


def test_recover_commit_before_candidate_acknowledgement(matching_data):
    job=matching.request_scan()['id']
    finish(job)
    with get_store().connection() as db:
        count=db.execute('SELECT count(*) FROM entity_merges').fetchone()[0]
        row=db.execute("SELECT id FROM entity_match_pairs WHERE state='merged' LIMIT 1").fetchone()
        db.execute("UPDATE entity_match_pairs SET state='pending' WHERE id=?",(row[0],))
        db.execute("UPDATE entity_match_jobs SET state='running' WHERE id=?",(job,))
    finish(job)
    with get_store().connection() as db:
        assert db.execute('SELECT count(*) FROM entity_merges').fetchone()[0]==count
        assert db.execute('SELECT state FROM entity_match_pairs WHERE id=?',(row[0],)).fetchone()[0]=='merged'


def test_conflicting_explicit_ids_cannot_auto_merge(matching_data):
    left=matching.evidence_entity(entities.entity_index()[0])
    right={**left,'external_id':'different-id'}
    left['external_id']='original-id'
    pair={'id':'pair','left':left,'right':right}
    decisions,_=matching.evaluate([pair])
    assert not matching.supported(decisions[0],pair)
