from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest


@pytest.fixture
def agenda(monkeypatch, tmp_path):
    from modules.hfl_corpus import timeline as followups
    from workflows.hfl.timeline_store import FollowUpStore
    monkeypatch.setenv("HFL_TIMELINE_LOCAL_PREVIEW", "1")
    monkeypatch.setattr(followups, "write_completion", lambda *a, **kw: None)
    result = FollowUpStore(tmp_path / "agenda.sqlite3")
    monkeypatch.setattr(followups, "store", lambda: result)
    return result


def payload(**extra):
    return {"request_id": str(uuid4()), "title": "Investigate Essential Space", "expected_outcome": "Record a feasible sync route or explain why none exists.", "review_date": (date.today()+timedelta(days=1)).isoformat(), "due_date": (date.today()+timedelta(days=7)).isoformat(), **extra}


def test_lifecycle_persists_completion_and_reopen_history(agenda, authenticated_client):
    created = authenticated_client.post("/hfl-corpus/timeline/items", json=payload()).json()["item"]
    completed = authenticated_client.patch(f"/hfl-corpus/timeline/items/{created['id']}", json={"version": 1, "status": "done", "completion_note": "Export verified."})
    assert completed.status_code == 200
    assert completed.json()["item"]["completed_at"]
    assert authenticated_client.get("/hfl-corpus/timeline/items").json()["items"] == []
    assert len(authenticated_client.get("/hfl-corpus/timeline/items?closed=true").json()["items"]) == 1
    reopened = authenticated_client.patch(f"/hfl-corpus/timeline/items/{created['id']}", json={"version": 2, "status": "active"}).json()["item"]
    assert reopened["completed_at"] == ""
    from workflows.hfl.timeline_store import FollowUpStore
    assert FollowUpStore(agenda.path).get(created["id"])["status"] == "active"
    history = authenticated_client.get(f"/hfl-corpus/timeline/items/{created['id']}/history").json()["history"]
    assert [row["item"]["status"] for row in history] == ["active", "done", "open"]
    assert history[1]["item"]["completion_note"] == "Export verified."


def test_creation_retry_after_completion_does_not_duplicate_or_reopen(agenda, authenticated_client):
    data = payload()
    first = authenticated_client.post("/hfl-corpus/timeline/items", json=data).json()["item"]
    authenticated_client.patch(f"/hfl-corpus/timeline/items/{first['id']}", json={"version": 1, "status": "done"})
    retry = authenticated_client.post("/hfl-corpus/timeline/items", json=data)
    assert retry.status_code == 200
    assert retry.json()["duplicate"] is True
    assert retry.json()["item"]["status"] == "done"
    assert len(agenda.history(first["id"])) == 2
    assert authenticated_client.post("/hfl-corpus/timeline/items", json={**data, "title": "Different"}).status_code == 409


def test_stale_edit_cannot_overwrite_completion(agenda, authenticated_client):
    item = authenticated_client.post("/hfl-corpus/timeline/items", json=payload()).json()["item"]
    url = f"/hfl-corpus/timeline/items/{item['id']}"
    assert authenticated_client.patch(url, json={"version": 1, "status": "done"}).status_code == 200
    assert authenticated_client.patch(url, json={"version": 1, "title": "Stale edit"}).status_code == 409
    assert agenda.get(item["id"])["status"] == "done"
    assert len(agenda.history(item["id"])) == 2


@pytest.mark.parametrize("extra", [{"title": " "}, {"expected_outcome": ""}, {"review_date": "2026-02-30"}, {"due_date": "tomorrow"}, {"status": "done"}, {"execute": "arbitrary.task"}])
def test_invalid_creation_writes_nothing(agenda, authenticated_client, extra):
    assert authenticated_client.post("/hfl-corpus/timeline/items", json=payload(**extra)).status_code == 400
    assert agenda.list() == []


def test_review_dates_do_not_become_overdue_deadlines(agenda, authenticated_client):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Asia/Singapore")).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    tomorrow = (today + timedelta(days=1)).isoformat()
    for title, fields in [("Review", {"review_date": yesterday}), ("Deadline", {"due_date": yesterday}), ("Future", {"review_date": tomorrow})]:
        authenticated_client.post("/hfl-corpus/timeline/items", json=payload(title=title, **fields))
    items = authenticated_client.get("/hfl-corpus/timeline/items").json()["items"]
    assert [(item["title"], item["group"]) for item in items] == [("Deadline", "Overdue"), ("Review", "Today"), ("Future", "Upcoming")]
    assert items[1]["overdue"] is False


def test_evidence_is_resolved_by_guid_after_reorder_and_rechecks_protection(agenda, authenticated_client, monkeypatch):
    from modules.hfl_corpus import router as corpus
    from modules.hfl_corpus.corpus import CorpusEntry
    entry = CorpusEntry(anchor="hfl-entry-1-old", header="2026-09-09", moment="Research", what_happened="Evidence", tags=(), text="Entry ID: hfl-test-evidence\nMoment: Research")
    document = SimpleNamespace(entries=(entry,))
    monkeypatch.setattr(corpus, "_uses_remote_corpus", lambda: False)
    monkeypatch.setattr(corpus.corpus_index, "get", lambda _: document)
    source = {"path": "2026-09-09.md", "entry_id": "hfl-test-evidence"}
    response = authenticated_client.post("/hfl-corpus/timeline/items", json=payload(source=source))
    assert response.status_code == 201
    assert response.json()["item"]["source"]["title"] == "Research"
    document.entries = (replace(entry, anchor="hfl-entry-9-new"),)
    url = "/hfl-corpus/timeline/evidence?path=2026-09-09.md&entry_id=hfl-test-evidence"
    response = authenticated_client.get(url, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].endswith("#hfl-entry-9-new")
    monkeypatch.setattr(corpus, "is_secret_entry", lambda *_: True)
    assert authenticated_client.get(url).status_code == 404
    assert authenticated_client.post("/hfl-corpus/timeline/items", json=payload(source=source)).status_code == 404


def test_owner_auth_required_for_reads_writes_and_history(agenda):
    from main import app
    from fastapi.testclient import TestClient
    with TestClient(app) as client:
        assert client.get("/hfl-corpus/timeline/items").status_code == 401
        assert client.post("/hfl-corpus/timeline/items", json=payload()).status_code == 401
        assert client.patch("/hfl-corpus/timeline/items/followup-x", json={"version": 1}).status_code == 401
        assert client.get("/hfl-corpus/timeline/items/followup-x/history").status_code == 401


def test_concurrent_updates_only_one_wins(agenda):
    from concurrent.futures import ThreadPoolExecutor
    from workflows.hfl.timeline_store import FollowUpConflict
    item, _ = agenda.create(payload(), actor="owner")
    def update(status):
        try:
            agenda.update(item["id"], {"version": 1, "status": status}, actor="owner")
            return "saved"
        except FollowUpConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(update, ["done", "dismissed"])) == ["conflict", "saved"]
    assert len(agenda.history(item["id"])) == 2


def suggestion():
    source = {'path': '2026-09-09.md', 'entry_id': 'hfl-test', 'title': 'Research', 'date': '2026-09-09'}
    return {'category': 'recommendations', 'title': 'Check the export route', 'evidence': [source], 'source': source, 'expected_outcome': 'Record feasibility', 'recommendation': 'Record feasibility', 'resolution_check': 'No completion found', 'confidence': 'medium'}


def cache(agenda):
    run = agenda.claim_period('2026-09-09', '2026-09-09', force=True)
    agenda.save_suggestions('2026-09-09', '2026-09-09', run, [suggestion()], {})
    return agenda.suggestions('2026-09-09', '2026-09-09')[0]


def test_cached_browsing_does_not_investigate(agenda, authenticated_client, monkeypatch):
    from modules.hfl_corpus import timeline
    monkeypatch.setattr(timeline, 'explore_period', lambda *a, **kw: pytest.fail('Browsing must not analyze'))
    cache(agenda)
    for _ in range(2):
        result = authenticated_client.get('/hfl-corpus/timeline/period?start=2026-09-09&end=2026-09-09')
        assert result.status_code == 200
        assert len(result.json()['suggestions']) == 1


def test_dismissal_survives_regeneration_and_refresh_removes_stale(agenda):
    item = cache(agenda)
    agenda.mark_suggestion(item['id'], 'dismissed')
    run = agenda.claim_period('2026-09-09', '2026-09-09', force=True)
    agenda.save_suggestions('2026-09-09', '2026-09-09', run, [suggestion()], {})
    assert agenda.suggestions('2026-09-09', '2026-09-09') == []
    assert agenda.suggestion(item['id'])['status'] == 'dismissed'
    run = agenda.claim_period('2026-09-09', '2026-09-09', force=True)
    agenda.save_suggestions('2026-09-09', '2026-09-09', run, [], {})
    assert agenda.suggestions('2026-09-09', '2026-09-09', include_dismissed=True) == []


def test_concurrent_adoption_creates_one_action(agenda):
    from concurrent.futures import ThreadPoolExecutor
    item = cache(agenda)
    def adopt(_):
        return agenda.create(payload(), actor='owner', source=item['source'], suggestion_id=item['id'])[0]['id']
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(set(pool.map(adopt, range(2)))) == 1
    assert len(agenda.list()) == 1
    assert agenda.suggestion(item['id'])['status'] == 'adopted'


def test_markers_and_period_follow_source_plan_and_history(agenda, authenticated_client):
    future = (date.today()+timedelta(days=20)).isoformat()
    item, _ = agenda.create(payload(due_date=future, review_date=future), actor='owner', source=suggestion()['source'])
    markers = authenticated_client.get('/hfl-corpus/timeline/markers').json()['days']
    assert markers[future] == {'planned': [item['id']], 'actions': [], 'dot_status':'open'}
    assert markers['2026-09-09']['actions'] == [item['id']]
    assert 'count' not in markers[future]
    result = authenticated_client.get(f'/hfl-corpus/timeline/period?start={future}&end={future}').json()
    assert result['items'][0]['id'] == item['id']
    agenda.update(item['id'], {'version': 1, 'status': 'done'}, actor='owner')
    markers = authenticated_client.get('/hfl-corpus/timeline/markers').json()['days']
    assert markers[future] == {'planned': [item['id']], 'actions': [], 'dot_status':'done'}


def test_run_claim_and_failure_preserve_cached_evidence(agenda):
    cache(agenda)
    run = agenda.claim_period('2026-09-09','2026-09-09', force=True)
    assert agenda.claim_period('2026-09-09','2026-09-09', force=True) is None
    assert agenda.start_period('2026-09-09','2026-09-09',run)
    assert not agenda.start_period('2026-09-09','2026-09-09',run)
    agenda.finish_period('2026-09-09','2026-09-09',run,{},state='failed')
    assert len(agenda.suggestions('2026-09-09','2026-09-09')) == 1
    assert not agenda.save_suggestions('2026-09-09','2026-09-09','stale',[],{})


def test_completion_receipt_retries_with_stable_identity(agenda):
    from workflows.hfl.timeline import write_completion
    item,_ = agenda.create(payload(),actor='owner',source=suggestion()['source'])
    agenda.update(item['id'], {'version':1, 'status':'done', 'completion_note':'Export checked'},actor='owner')
    seen=[]
    def submit(entry, **kwargs):
        seen.append(kwargs['dedup_key'])
        assert 'Export checked' in entry.what_happened
        return {'delivery':'outbox' if len(seen)==1 else 'forwarded'}
    write_completion(item['id'],2,store=agenda,submit=submit)
    assert len(agenda.receipts(pending_only=True)) == 1
    write_completion(item['id'],2,store=agenda,submit=submit)
    assert agenda.receipts(pending_only=True) == []
    assert seen[0] == seen[1]


def test_analysis_validates_evidence_and_skips_resolved(agenda):
    from workflows.hfl.timeline import explore_period
    row={'entry_id':'hfl-test','path':'2026-09-09.md','when':'2026-09-09T12:00:00+08:00','moment':'Research export','what_happened':'Investigate it','source':'notes'}
    finding={**suggestion(),'evidence':['N1'],'status':'open','severity':'low','latest_evidence':['N1']}
    result=explore_period('2026-09-09','2026-09-09',store=agenda,collect=lambda *a:([row],{}),related=lambda *a:[],analyze=lambda *a,**kw:{'findings':[finding,{**finding,'title':'Already done','status':'resolved'},{**finding,'title':'Invented','evidence':['N99']}]})
    assert result['suggestions'] == 1
    assert agenda.suggestions('2026-09-09','2026-09-09')[0]['source']['entry_id'] == 'hfl-test'


@pytest.mark.parametrize('start,end',[('2026-01-01','2026-03-01'),('bad','bad'),('2026-09-09','2026-09-08')])
def test_invalid_period_rejected_without_work(agenda,authenticated_client,start,end):
    assert authenticated_client.get('/hfl-corpus/timeline/period',params={'start':start,'end':end}).status_code == 400
    assert authenticated_client.post('/hfl-corpus/timeline/explore',json={'start':start,'end':end}).status_code == 400


def test_canonical_api_requires_bearer_even_with_owner_session(agenda, authenticated_client):
    url='/api/hfl/timeline/markers'
    assert authenticated_client.get(url).status_code == 401
    response=authenticated_client.get(url,headers={'Authorization':'Bearer frontend-test-hfl-api-token'})
    assert response.status_code == 200
    assert response.json() == {'days':{}}


def test_remote_timeline_uses_canonical_route_without_browser_cookie(agenda,authenticated_client,monkeypatch):
    import httpx
    from modules.hfl_corpus import timeline
    monkeypatch.delenv('HFL_TIMELINE_LOCAL_PREVIEW')
    monkeypatch.setattr(timeline,'get_settings',lambda:SimpleNamespace(hfl_corpus_api_url='https://canonical.test',hfl_corpus_api_token='test-token'))
    calls=[]
    class Remote:
        def __init__(self,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def request(self,method,url,**kwargs):
            calls.append((method,url,kwargs))
            return httpx.Response(200,json={'days':{}})
    monkeypatch.setattr(timeline.httpx,'AsyncClient',Remote)
    assert authenticated_client.get('/hfl-corpus/timeline/markers').status_code == 200
    assert calls[0][1] == 'https://canonical.test/api/hfl/timeline/markers'
    assert calls[0][2]['headers'] == {'Authorization':'Bearer test-token','Content-Type':'application/json'}


def test_daily_job_selects_previous_singapore_day(agenda,monkeypatch):
    import importlib, inspect
    from datetime import datetime
    task=importlib.import_module('workflows.hfl.tasks.timeline_suggestions')
    class Clock:
        @staticmethod
        def now(zone): return datetime(2026,9,11,4,15,tzinfo=zone)
    monkeypatch.setattr(task,'datetime',Clock)
    monkeypatch.setattr(task,'FollowUpStore',lambda path:agenda)
    seen=[]
    monkeypatch.setattr(task,'explore_period',lambda *args,**kwargs:seen.append(args) or {})
    inspect.unwrap(task.generate_timeline_suggestions.run)()
    assert seen == [('2026-09-10','2026-09-10')]


def test_related_recall_reads_entries_contract_and_later_outcomes(monkeypatch):
    from workflows.hfl import timeline
    from workflows.hfl.tasks import activity_radar
    monkeypatch.setattr(activity_radar,'infer_topics',lambda *a,**kw:['export'])
    monkeypatch.setattr(timeline,'parsed_row',lambda match, **kwargs: {'entry_id':match['entry']['id'],'path':match['relative_path']})
    calls=[]
    class Client:
        def _raw_request(self,method,path,**kwargs):
            calls.append(path)
            if path.startswith('day-matches/'):
                data={'matches':[{'relative_path':'later.md','entry':{'id':'hfl-later'}}]}
            elif path == 'documents':
                assert kwargs['params']['date_field'] == 'entry'
                data={'results':[{'relative_path':'history.md'}]}
            else:
                data={'entries':[{'id':'hfl-historical'}]}
            return SimpleNamespace(json=lambda:data)
    result=timeline.collect_related([{'entry_id':'hfl-source','tags':[]}],'2026-09-09',client=Client())
    assert {row['entry_id'] for row in result} == {'hfl-later','hfl-historical'}


def test_completion_can_inform_recall_but_cannot_generate_its_own_idea():
    from workflows.hfl.timeline import parsed_row
    match={'relative_path':'2026-09-11.md','entry':{'header':'2026-09-11','text':'Entry ID: hfl-receipt\nSource: hfl-followup-outcome\nMoment: Completed export\nWhat happened: Verified the export'}}
    assert parsed_row(match) is None
    assert parsed_row(match,include_outcomes=True)['entry_id'] == 'hfl-receipt'
    match['entry']['secret']=True
    assert parsed_row(match,include_outcomes=True) is None


def test_preview_completion_stays_local(agenda,monkeypatch):
    from workflows.hfl.timeline import write_completion
    from workflows.hfl import persistence
    monkeypatch.setattr(persistence,'submit_hfl_entry',lambda *a,**kw:pytest.fail('Preview must not write the corpus'))
    item,_=agenda.create(payload(),actor='owner')
    agenda.update(item['id'],{'version':1,'status':'done'},actor='owner')
    result=write_completion(item['id'],2,store=agenda)
    assert result['delivery'] == 'preview'
    assert agenda.receipts(pending_only=True) == []


def test_action_prompt_persists_markdown_and_revision_history(agenda, authenticated_client):
    prompt = '    Indented Markdown\n\n# Goal\n\n- Check the export path\n- Preserve source links\n\n```text\nDo not execute yet.\n```'
    result=authenticated_client.post('/hfl-corpus/timeline/items',json=payload(prompt=prompt))
    assert result.status_code == 201
    item=result.json()['item']
    assert item['prompt'] == prompt
    assert agenda.get(item['id'])['prompt'] == prompt
    edited=authenticated_client.patch('/hfl-corpus/timeline/items/'+item['id'],json={'version':1,'prompt':'## Revised instructions'})
    assert edited.status_code == 200
    assert agenda.history(item['id'])[0]['item']['prompt'] == '## Revised instructions'
    assert agenda.history(item['id'])[1]['item']['prompt'] == prompt
    assert authenticated_client.patch('/hfl-corpus/timeline/items/'+item['id'],json={'version':2,'prompt':''}).status_code == 200
    assert agenda.get(item['id'])['prompt'] == ''


@pytest.mark.parametrize('prompt',[123,'x'*20001])
def test_action_prompt_rejects_invalid_values(agenda,authenticated_client,prompt):
    assert authenticated_client.post('/hfl-corpus/timeline/items',json=payload(prompt=prompt)).status_code == 400
    assert agenda.list() == []


@pytest.mark.parametrize('mode',['omitted','blank'])
def test_complete_by_is_optional_on_creation(agenda,authenticated_client,mode):
    data=payload()
    if mode=='omitted': data.pop('due_date')
    else: data['due_date']=''
    response=authenticated_client.post('/hfl-corpus/timeline/items',json=data)
    assert response.status_code == 201
    assert response.json()['item']['due_date'] == ''
    assert agenda.list()[0]['due_date'] == ''


def test_clearing_complete_by_removes_deadline_dot_and_preserves_review(agenda,authenticated_client):
    review=(date.today()+timedelta(days=2)).isoformat()
    due=(date.today()+timedelta(days=10)).isoformat()
    item=authenticated_client.post('/hfl-corpus/timeline/items',json=payload(review_date=review,due_date=due)).json()['item']
    response=authenticated_client.patch('/hfl-corpus/timeline/items/'+item['id'],json={'version':1,'due_date':''})
    assert response.status_code == 200
    assert agenda.get(item['id'])['due_date'] == ''
    assert agenda.history(item['id'])[1]['item']['due_date'] == due
    days=authenticated_client.get('/hfl-corpus/timeline/markers').json()['days']
    assert days[due]['dot_status'] is None
    assert days[review]['dot_status'] == 'open'


def test_undated_action_can_be_dismissed(agenda,authenticated_client):
    item,_=agenda.create(payload(review_date='',due_date=''),actor='owner')
    response=authenticated_client.patch('/hfl-corpus/timeline/items/'+item['id'],json={'version':1,'status':'dismissed'})
    assert response.status_code == 200
    assert response.json()['item']['due_date'] == ''


def test_review_on_is_optional_and_can_be_cleared(agenda,authenticated_client):
    data=payload()
    data.pop('review_date')
    response=authenticated_client.post('/hfl-corpus/timeline/items',json=data)
    assert response.status_code==201
    item=response.json()['item']
    assert item['review_date']==''
    url='/hfl-corpus/timeline/items/'+item['id']
    assert authenticated_client.patch(url,json={'version':1,'review_date':data['due_date']}).status_code==200
    response=authenticated_client.patch(url,json={'version':2,'review_date':''})
    assert response.status_code==200
    assert response.json()['item']['review_date']==''
    assert response.json()['item']['due_date']==data['due_date']


@pytest.mark.parametrize('statuses,expected',[
    (['open'],'open'), (['active'],'open'), (['in_progress'],'in_progress'),
    (['in_progress','in_progress'],'in_progress'), (['done'],'done'),
    (['done','done'],'done'), (['done','in_progress'],'in_progress'),
    (['open','in_progress'],'open'), (['active','done'],'open'),
    (['open','in_progress','done'],'open'), (['dismissed'],None),
    (['dismissed','in_progress'],'in_progress'), (['dismissed','done'],'done'),
])
def test_date_dot_aggregates_current_statuses(agenda,authenticated_client,statuses,expected):
    scheduled=(date.today()+timedelta(days=15)).isoformat()
    for status in statuses:
        item,_=agenda.create(payload(review_date=scheduled,due_date=scheduled),actor='owner')
        if status!='open': agenda.update(item['id'],{'version':1,'status':status},actor='owner')
    day=authenticated_client.get('/hfl-corpus/timeline/markers').json()['days'][scheduled]
    assert day['dot_status']==expected
    assert len(day['planned'])==sum(status!='dismissed' for status in statuses)
    assert 'count' not in day


def test_reschedule_and_reopen_update_dots(agenda,authenticated_client):
    first=(date.today()+timedelta(days=15)).isoformat()
    second=(date.today()+timedelta(days=16)).isoformat()
    item,_=agenda.create(payload(review_date=first,due_date=second),actor='owner')
    agenda.update(item['id'],{'version':1,'status':'done'},actor='owner')
    days=authenticated_client.get('/hfl-corpus/timeline/markers').json()['days']
    assert days[first]['dot_status']==days[second]['dot_status']=='done'
    agenda.update(item['id'],{'version':2,'status':'in_progress','review_date':'','due_date':second},actor='owner')
    days=authenticated_client.get('/hfl-corpus/timeline/markers').json()['days']
    assert days[first]['dot_status'] is None
    assert days[second]['dot_status']=='in_progress'


def test_waiting_records_migrate_to_in_progress_without_losing_history(agenda):
    import json
    from workflows.hfl.timeline_store import FollowUpStore
    item,_=agenda.create(payload(),actor='owner')
    item['status']='waiting'
    with agenda.connect() as db:
        db.execute("UPDATE followups SET status='waiting',payload=? WHERE id=?",(json.dumps(item),item['id']))
    migrated=FollowUpStore(agenda.path)
    assert migrated.get(item['id'])['status']=='in_progress'
    assert migrated.get(item['id'])['version']==1
    assert len(migrated.history(item['id']))==1
    assert FollowUpStore(agenda.path).get(item['id'])['status']=='in_progress'


def high_idea(agenda,title='Verify the phone export',start='2026-09-09'):
    item={**suggestion(),'title':title,'confidence':'high','status':'uncertain'}
    run=agenda.claim_period(start,start,force=True)
    agenda.save_suggestions(start,start,run,[item],{})
    return agenda.suggestions(start,start)[0]


def create_decision(item):
    return {'suggestion_id':item['id'],'decision':'create','confidence':'high','completion_check':'clear','reason':'Concrete new feasibility check; no completion evidence or existing equivalent.'}


def test_high_confidence_auto_action_leaves_deadline_for_manual_review(agenda):
    from workflows.hfl.timeline import create_automatic_actions
    item=high_idea(agenda)
    # A previous deployment may have stored an offset; it must be ignored.
    with agenda.connect() as db:
        db.execute("CREATE TABLE timeline_settings (id INTEGER PRIMARY KEY, complete_after_days INTEGER)")
        db.execute("INSERT INTO timeline_settings VALUES (1,12)")
    result=create_automatic_actions('2026-09-09','2026-09-09',agenda,[],today=date(2026,9,12),review=lambda *args:[create_decision(item)])
    assert result['created']==1
    action=agenda.list()[0]
    assert action['review_date']=='2026-09-12'
    assert action['due_date']==''
    assert action['status']=='open'
    assert action['creation_mode']=='automatic'
    assert action['source']==item['source']
    assert action['prompt']==''
    assert agenda.history(action['id'])[0]['actor']=='timeline-automation'
    again=create_automatic_actions('2026-09-09','2026-09-09',agenda,[],review=lambda *args:pytest.fail('Already adopted'))
    assert again['created']==0
    assert agenda.get(action['id'])['due_date']==''


@pytest.mark.parametrize('status',['open','done','dismissed'])
def test_semantic_duplicate_preserves_existing_action(agenda,status):
    from workflows.hfl.timeline import create_automatic_actions
    action,_=agenda.create(payload(title='Test exporting phone notes'),actor='owner')
    if status!='open':action=agenda.update(action['id'],{'version':1,'status':status},actor='owner')
    item=high_idea(agenda,title='Validate Essential Space data extraction')
    def review(candidates,snapshot,evidence):
        assert snapshot['actions'][0]['title'] != candidates[0]['title']
        return [{'suggestion_id':item['id'],'decision':'duplicate','existing_action_id':action['id']}]
    result=create_automatic_actions('2026-09-09','2026-09-09',agenda,[],review=review)
    assert result['duplicates']==1
    assert agenda.get(action['id'])==action
    assert len(agenda.list()+agenda.list(closed=True))==1
    assert agenda.suggestion(item['id'])['followup_id']==action['id']


@pytest.mark.parametrize('change',[{'completion_check':'uncertain'},{'completion_check':'resolved'},{'confidence':'medium'},{'decision':'defer'},{'reason':''},{'decision':'duplicate','existing_action_id':'invented'}])
def test_auto_review_uncertainty_or_invalid_decision_keeps_idea(agenda,change):
    from workflows.hfl.timeline import create_automatic_actions
    item=high_idea(agenda)
    result=create_automatic_actions('2026-09-09','2026-09-09',agenda,[],review=lambda *args:[{**create_decision(item),**change}])
    assert result['created']==0
    assert agenda.list()==[]
    assert agenda.suggestion(item['id'])['status']=='suggested'


def test_auto_creation_rechecks_snapshot_after_concurrent_manual_change(agenda):
    from workflows.hfl.timeline import create_automatic_actions
    from workflows.hfl.timeline_store import FollowUpConflict
    item=high_idea(agenda)
    def review(*args):
        agenda.create(payload(),actor='owner')
        return [create_decision(item)]
    result=create_automatic_actions('2026-09-09','2026-09-09',agenda,[],review=review)
    assert result['state']=='failed'
    assert result['error']=='FollowUpConflict'
    assert len(agenda.list())==1
    assert agenda.suggestion(item['id'])['status']=='suggested'


def test_dismissed_idea_suppresses_reworded_recommendation(agenda):
    from workflows.hfl.timeline import create_automatic_actions
    previous=high_idea(agenda,title='Original idea')
    agenda.mark_suggestion(previous['id'],'dismissed')
    current=high_idea(agenda,title='Same outcome with different words')
    result=create_automatic_actions('2026-09-09','2026-09-09',agenda,[],review=lambda *args:[{'suggestion_id':current['id'],'decision':'duplicate','duplicate_suggestion_id':previous['id']}])
    assert result['duplicates']==1
    assert agenda.list()==[]
    assert agenda.suggestion(current['id'])['status']=='dismissed'


def test_analysis_chains_automatic_actions_and_keeps_cache_on_review_failure(agenda):
    from workflows.hfl.timeline import explore_period
    row={'entry_id':'hfl-test','path':'2026-09-09.md','when':'2026-09-09T12:00:00+08:00','moment':'Export','what_happened':'Explore export','source':'notes'}
    finding={**suggestion(),'confidence':'high','evidence':['N1'],'status':'uncertain','severity':'low','latest_evidence':['N1']}
    def fail(*args):raise RuntimeError('Review unavailable')
    result=explore_period('2026-09-09','2026-09-09',store=agenda,collect=lambda *args:([row],{}),related=lambda *args:[],analyze=lambda *args,**kwargs:{'findings':[finding]},auto_review=fail)
    assert result['state']=='complete'
    assert result['automatic_actions']['state']=='failed'
    assert len(agenda.suggestions('2026-09-09','2026-09-09'))==1
    assert agenda.list()==[]


def test_automatic_deadline_settings_are_removed(agenda,authenticated_client):
    page=authenticated_client.get('/profile')
    assert page.status_code==200
    assert 'Complete automatic actions after' not in page.text
    assert 'second-brain-settings' not in page.text
    assert authenticated_client.get('/hfl-corpus/timeline/settings').status_code==404
    assert authenticated_client.patch('/hfl-corpus/timeline/settings',json={'complete_after_days':14}).status_code==404


def test_explore_chains_creation_with_review_only(agenda):
    from workflows.hfl.timeline import explore_period,SGT
    from datetime import datetime
    row={'entry_id':'hfl-test','path':'2026-09-09.md','when':'2026-09-09T12:00:00+08:00','moment':'Export','what_happened':'Explore export','source':'notes'}
    finding={**suggestion(),'confidence':'high','evidence':['N1'],'status':'uncertain','severity':'low','latest_evidence':['N1']}
    result=explore_period('2026-09-09','2026-09-09',store=agenda,collect=lambda *args:([row],{}),related=lambda *args:[],analyze=lambda *args,**kwargs:{'findings':[finding]},auto_review=lambda candidates,*args:[create_decision(candidates[0])])
    assert result['automatic_actions']['created']==1
    action=agenda.list()[0]
    today=datetime.now(SGT).date()
    assert action['review_date']==today.isoformat()
    assert action['due_date']==''
    assert agenda.run_for('2026-09-09','2026-09-09')['result']['automatic_actions']['created']==1


def test_duplicate_candidates_in_one_batch_create_only_one_action(agenda):
    from workflows.hfl.timeline import create_automatic_actions
    first={**suggestion(),'title':'First phrasing','confidence':'high'}
    second={**suggestion(),'title':'Another phrasing','confidence':'high'}
    run=agenda.claim_period('2026-09-09','2026-09-09')
    agenda.save_suggestions('2026-09-09','2026-09-09',run,[first,second],{})
    def review(candidates,*args):
        return [create_decision(candidates[0]),{'suggestion_id':candidates[1]['id'],'decision':'duplicate','duplicate_suggestion_id':candidates[0]['id'],'reason':'Same outcome.'}]
    result=create_automatic_actions('2026-09-09','2026-09-09',agenda,[],review=review)
    assert result['created']==result['duplicates']==1
    assert len(agenda.list())==1
