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
    return {"request_id": str(uuid4()), "title": "Investigate Essential Space", "expected_outcome": "Record a feasible sync route or explain why none exists.", **extra}


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
    for title, fields in [("Review", {"review_date": yesterday}), ("Deadline", {"due_date": yesterday}), ("Future", {"review_date": tomorrow}), ("Undated", {})]:
        authenticated_client.post("/hfl-corpus/timeline/items", json=payload(title=title, **fields))
    items = authenticated_client.get("/hfl-corpus/timeline/items").json()["items"]
    assert [(item["title"], item["group"]) for item in items] == [("Deadline", "Overdue"), ("Review", "Today"), ("Future", "Upcoming"), ("Undated", "Unscheduled")]
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
    assert markers[future] == {'planned': [item['id']], 'actions': []}
    assert markers['2026-09-09']['actions'] == [item['id']]
    assert 'count' not in markers[future]
    result = authenticated_client.get(f'/hfl-corpus/timeline/period?start={future}&end={future}').json()
    assert result['items'][0]['id'] == item['id']
    agenda.update(item['id'], {'version': 1, 'status': 'done'}, actor='owner')
    markers = authenticated_client.get('/hfl-corpus/timeline/markers').json()['days']
    assert markers[future] == {'planned': [], 'actions': [item['id']]}


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
