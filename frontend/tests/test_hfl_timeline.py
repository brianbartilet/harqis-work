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


@pytest.mark.parametrize('width', [390, 1100])
def test_day_menu_creates_action_due_on_selected_date(agenda, authenticated_client, monkeypatch, tmp_path, width):
    from urllib.parse import urlparse
    import modules.hfl_corpus.router as corpus
    playwright = pytest.importorskip('playwright.sync_api')
    from modules.hfl_corpus import corpus as index_module
    for offset in (-1, 0):
        day = (date.today() + timedelta(days=offset)).isoformat()
        (tmp_path / f'{day}.md').write_text(f'## {day} 09:00\nMoment: Test activity\nSource: notes\n', encoding='utf-8')
    monkeypatch.setattr(index_module, 'resolve_corpus_root', lambda: tmp_path)
    monkeypatch.setattr(corpus, 'corpus_index', index_module.CorpusIndex())
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 1000})

        def route(request_route):
            request = request_route.request
            url = urlparse(request.url)
            if url.hostname != 'timeline.test':
                request_route.abort()
                return
            response = authenticated_client.request(
                request.method, url.path + ('?' + url.query if url.query else ''),
                content=request.post_data,
                headers={key: value for key, value in request.headers.items()
                         if key.lower() in {'content-type', 'x-csrf-token'}},
            )
            request_route.fulfill(status=response.status_code, body=response.content,
                                  headers={'content-type': response.headers.get('content-type', 'text/html')})

        page.route('**/*', route)
        page.goto('https://timeline.test/hfl-corpus')
        form = page.locator('#followup-form')
        for offset in (-1, 0, 1):
            selected = (date.today() + timedelta(days=offset)).isoformat()
            page.locator(f'[data-activity-day="{selected}"]').click()
            playwright.expect(page.locator('[data-activity-menu-actions]')).to_have_attribute('aria-expanded', 'true')
            playwright.expect(page.locator('[data-day-actions]')).to_be_visible()
            playwright.expect(page.locator('[data-activity-menu-matches]')).to_have_attribute('aria-expanded', 'false')
            if offset <= 0:
                page.locator('[data-activity-menu-matches]').click()
                playwright.expect(page.locator('[data-activity-menu-matches]')).to_have_attribute('aria-expanded', 'true')
            else:
                page.locator('[data-activity-menu-actions]').click()
            page.keyboard.press('Escape')
            page.locator(f'[data-activity-day="{selected}"]').click()
            playwright.expect(page.locator('[data-activity-menu-actions]')).to_have_attribute('aria-expanded', 'true')
            playwright.expect(page.locator('[data-activity-menu-matches]')).to_have_attribute('aria-expanded', 'false')
            buttons = page.locator('.activity-day-quick-actions').locator('button, a')
            assert buttons.all_text_contents() == ['Entry', 'Action', 'Idea', 'Pin dates', 'Show document', 'Connections']
            create = page.locator('.activity-day-create > summary')
            create.click()
            playwright.expect(page.locator('[data-activity-menu-create-action]')).to_be_visible()
            page.keyboard.press('Escape')
            playwright.expect(page.locator('[data-activity-day-menu]')).to_be_visible()
            playwright.expect(page.locator('[data-activity-menu-create-action]')).to_be_hidden()
            create.click()
            page.locator('[data-activity-menu-create-action]').click()
            playwright.expect(page.locator('#followup-editor')).to_be_visible()
            playwright.expect(page.locator('[data-activity-day-menu]')).to_be_hidden()
            playwright.expect(page.locator('#followup-evidence')).to_be_hidden()
            assert form.locator('[name="due_date"]').input_value() == selected
            for name in ('title', 'expected_outcome', 'review_date', 'prompt', 'notes'):
                assert form.locator(f'[name="{name}"]').input_value() == ''
            form.locator('[name="title"]').fill('Manual action')
            if offset < 1:
                page.locator('#followup-editor [data-agenda-close]').first.click()
                page.get_by_role('button',name='Discard').click()
                assert agenda.list() == []
            else:
                form.locator('.action-details > summary').click()
                form.locator('[name="expected_outcome"]').fill('Record the result')
                form.locator('.action-triage:not(.action-details) > summary').click()
                form.locator('[name="matrix"]').select_option('Q2')
                form.locator('[name="matrix_confidence"]').select_option('medium')
                playwright.expect(form.locator('#matrix-help')).to_be_visible()
                form.locator('[type="submit"]').click()
                playwright.expect(form.locator('.editor-save-status')).to_have_text('Saved')
                form.locator('[data-agenda-close]').first.click()
                playwright.expect(page.locator('#followup-editor')).to_be_hidden()
        saved = agenda.list()
        assert len(saved) == 1
        assert saved[0]['title'] == 'Manual action'
        assert saved[0]['matrix'] == 'Q2'
        assert saved[0]['matrix_confidence'] == 'medium'
        assert saved[0]['review_date'] == ''
        assert saved[0]['due_date'] == selected
        assert not saved[0]['source']
        browser.close()


@pytest.mark.parametrize('width', [390, 1100])
def test_document_creates_multiple_actions_without_navigation(agenda, authenticated_client, monkeypatch, tmp_path, width):
    from urllib.parse import urlparse
    from modules.hfl_corpus import corpus, router
    playwright = pytest.importorskip('playwright.sync_api')
    document_path = tmp_path / '2026-09-14.md'
    document_path.write_text(
        '## 2026-09-14 09:00\nMoment: First entry\nEntry ID: hfl-first\n\n'
        '## 2026-09-14 10:00\nMoment: Second entry\nEntry ID: hfl-second\n', encoding='utf-8')
    monkeypatch.setattr(corpus, 'resolve_corpus_root', lambda: tmp_path)
    monkeypatch.setattr(router, 'corpus_index', corpus.CorpusIndex(ttl_seconds=0))
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def route(request_route):
            request = request_route.request
            url = urlparse(request.url)
            if url.hostname != 'document.test':
                request_route.abort()
                return
            response = authenticated_client.request(
                request.method, url.path + ('?' + url.query if url.query else ''),
                content=request.post_data,
                headers={key: value for key, value in request.headers.items()
                         if key.lower() in {'content-type', 'x-csrf-token'}},
            )
            request_route.fulfill(status=response.status_code, body=response.content,
                                  headers={'content-type': response.headers.get('content-type', 'text/html')})

        page.route('**/*', route)
        url = 'https://document.test/hfl-corpus/document/2026-09-14.md'
        page.goto(url)
        for index, title in enumerate(('First entry', 'Second entry')):
            page.locator('a.corpus-followup-action').nth(index).click()
            form = page.locator('#followup-form')
            playwright.expect(form.locator('[name="title"]')).to_have_value(title)
            assert form.locator('[name="expected_outcome"]').input_value() == ''
            playwright.expect(form.locator('.action-details')).not_to_have_attribute('open', '')
            form.locator('[type="submit"]').click()
            playwright.expect(form.locator('.action-details')).to_have_attribute('open', '')
            form.locator('[name="expected_outcome"]').fill('Record a useful result')
            form.locator('[type="submit"]').click()
            playwright.expect(page.locator('#followup-editor')).to_be_hidden()
            assert page.url == url
            confirmation = page.locator('.corpus-action-toast')
            playwright.expect(confirmation).to_be_visible()
            playwright.expect(confirmation).to_contain_text('View it in the Activity Corpus.')
            assert confirmation.evaluate('(el) => el.previousElementSibling.classList.contains("corpus-entry-header")')
            assert page.locator('dialog[open]').count() == 0
            confirmation.get_by_role('button', name='Dismiss action confirmation').click()
            playwright.expect(confirmation).to_be_hidden()
            playwright.expect(page.locator('a.corpus-followup-action').nth(index)).to_be_focused()
            assert page.locator('.corpus-action-feedback').count() == 0
        assert {item['source']['entry_id'] for item in agenda.list()} == {'hfl-first', 'hfl-second'}
        assert not errors
        browser.close()


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


@pytest.mark.parametrize('legacy', [False, True])
def test_evidence_is_resolved_by_guid_after_reorder_and_rechecks_protection(agenda, authenticated_client, monkeypatch, legacy):
    from modules.hfl_corpus import router as corpus
    from modules.hfl_corpus.corpus import CorpusEntry
    entry = CorpusEntry(anchor="hfl-entry-1-old", header="2026-09-09", moment="Research", what_happened="Evidence", tags=(), text="Entry ID: hfl-test-evidence\nMoment: Research")
    if legacy:
        entry = replace(entry, text="Moment: Research\nWhat happened: Evidence")
    from modules.hfl_corpus.timeline import entry_evidence_id
    evidence_id = entry_evidence_id(entry.text)
    document = SimpleNamespace(entries=(entry,))
    monkeypatch.setattr(corpus, "_uses_remote_corpus", lambda: False)
    monkeypatch.setattr(corpus.corpus_index, "get", lambda _: document)
    source = {"path": "2026-09-09.md", "entry_id": evidence_id}
    response = authenticated_client.post("/hfl-corpus/timeline/items", json=payload(source=source))
    assert response.status_code == 201
    assert response.json()["item"]["source"]["title"] == "Research"
    document.entries = (replace(entry, anchor="hfl-entry-9-new"),)
    url = "/hfl-corpus/timeline/evidence?path=2026-09-09.md&entry_id=" + evidence_id
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
    (['incomplete'],'incomplete'), (['incomplete','open','in_progress','done'],'incomplete'),
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


def test_incomplete_history_action_overrides_completed_schedule(agenda, authenticated_client, monkeypatch):
    import modules.hfl_corpus.timeline as timeline

    selected = '2026-09-13'
    incomplete, _ = agenda.create(payload(review_date='2026-09-14', due_date=''), actor='owner')
    agenda.update(incomplete['id'], {'version': 1, 'status': 'incomplete'}, actor='owner')
    complete, _ = agenda.create(payload(review_date=selected, due_date=''), actor='owner')
    agenda.update(complete['id'], {'version': 1, 'status': 'done'}, actor='owner')
    original_events = timeline.item_events

    def events(item, canonical):
        result = original_events(item, canonical)
        if item['id'] == incomplete['id']:
            result.append({'date': selected, 'kind': 'done', 'version': 1})
        return result

    monkeypatch.setattr(timeline, 'item_events', events)
    day = authenticated_client.get('/hfl-corpus/timeline/markers').json()['days'][selected]
    assert incomplete['id'] in day['actions']
    assert complete['id'] in day['planned']
    assert day['dot_status'] == 'incomplete'
    agenda.update(incomplete['id'], {'version': 2, 'status': 'done'}, actor='owner')
    day = authenticated_client.get('/hfl-corpus/timeline/markers').json()['days'][selected]
    assert day['dot_status'] == 'done'


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


def test_matrix_roundtrip_validation_history_and_combined_order(agenda, authenticated_client):
    url = '/hfl-corpus/timeline/items'
    for matrix in ['Q3', 'Q2', 'Q1', 'Q4', '']:
        response = authenticated_client.post(url, json=payload(matrix=matrix, matrix_confidence='high' if matrix else '', matrix_reason='Owner goals' if matrix else ''))
        assert response.status_code == 201
    done = agenda.list()[0]
    agenda.update(done['id'], {'version': 1, 'status': 'done'}, actor='owner')
    items = authenticated_client.get(url+'?include_closed=true').json()['items']
    assert [item['matrix'] for item in items] == ['Q1', 'Q2', 'Q3', 'Q4', '']
    assert items[-1]['status'] == 'done'
    assert not items[-1]['overdue']
    item = items[0]
    changed = authenticated_client.patch(url+'/'+item['id'], json={'version':1, 'matrix':'Q2', 'matrix_confidence':'low', 'matrix_reason':'Deadline removed'})
    assert changed.status_code == 200
    assert agenda.get(item['id'])['matrix_confidence'] == 'low'
    assert agenda.history(item['id'])[1]['item']['matrix'] == 'Q1'
    assert authenticated_client.patch(url+'/'+item['id'], json={'version':1,'matrix':'Q4'}).status_code == 409
    for fields in [{'matrix':'Q5'}, {'matrix':[]}, {'matrix':'Q2','matrix_confidence':'certain'}, {'matrix_confidence':'high'}, {'matrix':'Q1','matrix_reason':300}]:
        assert authenticated_client.post(url, json=payload(**fields)).status_code == 400


def test_matrix_survives_analysis_and_automatic_creation(agenda):
    from workflows.hfl.timeline import explore_period
    finding = {**suggestion(), 'confidence':'high', 'evidence':['N1'], 'latest_evidence':['N1'], 'status':'uncertain', 'severity':'low',
               'matrix':'Q2', 'matrix_confidence':'medium', 'matrix_reason':'Prevention with no deadline'}
    result = explore_period('2026-09-09','2026-09-09',store=agenda,
        collect=lambda *a: ([{'entry_id':'hfl-priority','path':'2026-09-09.md','when':'2026-09-09T12:00:00+08:00','moment':'Planning','what_happened':'Plan prevention','source':'notes'}], {}), related=lambda *a: [],
        analyze=lambda *a,**kw: {'findings':[finding]},
        auto_review=lambda candidates,*a: [create_decision(item) for item in candidates])
    assert result['state'] == 'complete'
    item = agenda.list()[0]
    assert (item['matrix'], item['matrix_confidence'], item['matrix_reason']) == ('Q2','medium','Prevention with no deadline')


@pytest.mark.parametrize('width', [390, 1100])
def test_unified_actions_matrix_editor_and_empty_message(agenda, authenticated_client, monkeypatch, tmp_path, width):
    from urllib.parse import urlparse
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from modules.hfl_corpus import router
    playwright = pytest.importorskip('playwright.sync_api')
    monkeypatch.setattr(router.corpus_index, 'documents', lambda **kwargs: ())
    today = datetime.now(ZoneInfo('Asia/Singapore')).date().isoformat()
    for title, matrix in [('Interruption', 'Q3'), ('Prevention', 'Q2'), ('Completed work', 'Q1')]:
        item = agenda.create(payload(title=title, matrix=matrix, matrix_confidence='medium', due_date=today), actor='owner')[0]
        if title == 'Completed work':
            agenda.update(item['id'], {'version':1, 'status':'done'}, actor='owner')
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width':width, 'height':1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def route(request_route):
            request = request_route.request
            url = urlparse(request.url)
            if url.hostname != 'timeline.test':
                request_route.abort(); return
            response = authenticated_client.request(request.method, url.path+('?' + url.query if url.query else ''), content=request.post_data,
                headers={key:value for key,value in request.headers.items() if key.lower() in {'content-type','x-csrf-token'}})
            request_route.fulfill(status=response.status_code, body=response.content, headers={'content-type':response.headers.get('content-type','text/html')})
        page.route('**/*', route)
        page.goto('https://timeline.test/hfl-corpus')
        page.locator(f'[data-activity-day="{today}"]').click()
        playwright.expect(page.locator('[data-activity-menu-actions]')).to_have_attribute('aria-expanded', 'true')
        cards = page.locator('#agenda-items .agenda-card')
        playwright.expect(cards).to_have_count(3)
        assert cards.locator('h3').all_text_contents() == ['Prevention','Interruption','Completed work']
        assert page.locator('[data-agenda-closed]').count() == 0
        playwright.expect(page.locator('#agenda-explore')).to_be_visible()
        cards.first.get_by_role('button', name='Edit', exact=True).click()
        form = page.locator('#followup-form')
        playwright.expect(form.locator('[name="matrix"]')).to_have_value('Q2')
        playwright.expect(form.locator('[name="matrix_confidence"]')).to_have_value('medium')
        form.locator('.action-triage:not(.action-details) > summary').click()
        confidence_box = form.locator('[name="matrix_confidence"]').bounding_box()
        matrix_box = form.locator('[name="matrix"]').bounding_box()
        if width > 600:
            assert abs(confidence_box['y'] - matrix_box['y']) < 2
            assert confidence_box['x'] > matrix_box['x']
        page.screenshot(path=str(tmp_path / f'editor-{width}.png'))
        form.locator('[name="matrix"]').select_option('Q1')
        form.locator('[name="matrix_confidence"]').select_option('high')
        form.locator('[name="matrix_reason"]').fill('Important deadline confirmed')
        form.locator('[type="submit"]').click()
        playwright.expect(form.locator('.editor-save-status')).to_have_text('Saved')
        form.locator('[data-agenda-close]').first.click()
        playwright.expect(page.locator('#followup-editor')).to_be_hidden()
        playwright.expect(cards.first.locator('.action-matrix')).to_contain_text('Q1 · high confidence')
        menu_box = page.locator('[data-activity-day-menu]').bounding_box()
        header_box = page.locator('body > header').bounding_box()
        assert menu_box['y'] >= header_box['y'] + header_box['height']
        assert menu_box['y'] + menu_box['height'] <= page.viewport_size['height']
        assert menu_box['height'] <= 640
        page.screenshot(path=str(tmp_path / f'actions-{width}.png'))
        page.locator('[data-activity-menu-actions]').click()
        page.locator('[data-activity-day-menu-close]').click() if page.locator('[data-activity-day-menu-close]').count() else page.keyboard.press('Escape')
        empty_day = (datetime.now(ZoneInfo('Asia/Singapore')).date() - timedelta(days=10)).isoformat()
        page.locator(f'[data-activity-day="{empty_day}"]').click()
        if page.locator('[data-activity-menu-actions]').get_attribute('aria-expanded') != 'true':
            page.locator('[data-activity-menu-actions]').click()
        playwright.expect(page.locator('#agenda-items')).to_contain_text('No actions yet.')
        playwright.expect(page.locator('#agenda-items')).to_contain_text('Explore this period’s activity for ideas, then create an action.')
        playwright.expect(page.locator('#agenda-items').get_by_role('button', name='Explore ideas')).to_be_visible()
        assert not errors
        browser.close()


def test_manual_idea_adoption_preserves_matrix(agenda, authenticated_client, monkeypatch):
    from modules.hfl_corpus import timeline
    idea = {**suggestion(), 'matrix':'Q2', 'matrix_confidence':'low', 'matrix_reason':'Goals need clarification'}
    run = agenda.claim_period('2026-09-09','2026-09-09')
    agenda.save_suggestions('2026-09-09','2026-09-09',run,[idea],{})
    saved = agenda.suggestions('2026-09-09','2026-09-09')[0]
    async def evidence(*args):
        return SimpleNamespace(moment='Research', header='2026-09-09')
    monkeypatch.setattr(timeline,'evidence',evidence)
    response = authenticated_client.post('/hfl-corpus/timeline/items', json=payload(suggestion_id=saved['id']))
    assert response.status_code == 201
    assert response.json()['item']['matrix'] == 'Q2'
    assert response.json()['item']['matrix_confidence'] == 'low'


def test_followups_scope_filters_list_period_and_heatmap(agenda, authenticated_client, monkeypatch):
    import json
    from datetime import datetime, timezone
    from modules.hfl_corpus import router as corpus
    from modules.hfl_corpus.corpus import CorpusEntry
    stamp = datetime(2026, 9, 18, tzinfo=timezone.utc)
    entries = tuple(CorpusEntry(anchor=key, header='2026-09-18', moment=key,
        what_happened='Evidence', tags=('work',), source=source,
        text=f'Entry ID: hfl-{key}\nUseful evidence') for key, source in [('mail','email'),('note','notes')])
    document = SimpleNamespace(entries=entries, created_at=stamp, updated_at=stamp)
    monkeypatch.setattr(corpus, '_uses_remote_corpus', lambda: False)
    monkeypatch.setattr(corpus.corpus_index, 'get', lambda _: document)
    records = [agenda.create(payload(review_date='', due_date='2026-09-18'), actor='test',
        source={'path':'2026-09-18.md','entry_id':f'hfl-{key}','date':'2026-09-18'})[0] for key in ['mail','note']]
    manual = agenda.create(payload(review_date='', due_date='2026-09-18'), actor='test')[0]
    scope = json.dumps({'any':[{'source':'email'},{'source':'manual-entry'}]})
    params = {'scope':scope, 'q':'#work', 'date_field':'entry', 'date_from':'2026-09-18','date_to':'2026-09-18'}
    listing = authenticated_client.get('/hfl-corpus/timeline/items',params=params).json()
    assert [item['id'] for item in listing['items']] == [records[0]['id']]
    assert listing['items'][0]['sources'] == ['email']
    period = authenticated_client.get('/hfl-corpus/timeline/period',params={**params,'start':'2026-09-18','end':'2026-09-18'}).json()
    assert [item['id'] for item in period['items']] == [records[0]['id']]
    markers = authenticated_client.get('/hfl-corpus/timeline/markers',params=params).json()
    assert markers['days']['2026-09-18']['planned'] == [records[0]['id']]
    manual_list = authenticated_client.get('/hfl-corpus/timeline/items',params={'source':'manual-entry'}).json()['items']
    assert [item['id'] for item in manual_list] == [manual['id']]
    assert manual_list[0]['evidence_available'] is False
    assert authenticated_client.get('/hfl-corpus/timeline/items',params={'rolling':'bad'}).status_code == 422


def test_board_dismissal_cutoff_uses_transition_not_last_edit(agenda, authenticated_client, monkeypatch):
    from datetime import datetime, timedelta, timezone
    import workflows.hfl.timeline_store as storage
    old = (datetime.now(timezone.utc)-timedelta(days=20)).isoformat()
    monkeypatch.setattr(storage,'isoformat',lambda:old)
    item = agenda.create(payload(),actor='test')[0]
    item = agenda.update(item['id'],{'version':item['version'],'status':'dismissed'},actor='test')
    monkeypatch.setattr(storage,'isoformat',lambda:datetime.now(timezone.utc).isoformat())
    item = agenda.update(item['id'],{'version':item['version'],'title':'Edited recently'},actor='test')
    url='/hfl-corpus/timeline/items'
    assert authenticated_client.get(url,params={'include_closed':'true','recent_dismissed':'true'}).json()['items'] == []
    assert len(authenticated_client.get(url,params={'include_closed':'true'}).json()['items']) == 1
    item = agenda.update(item['id'],{'version':item['version'],'status':'open'},actor='test')
    agenda.update(item['id'],{'version':item['version'],'status':'dismissed'},actor='test')
    assert len(authenticated_client.get(url,params={'include_closed':'true','recent_dismissed':'true'}).json()['items']) == 1


@pytest.mark.parametrize('width', [390, 1440])
def test_followups_board_filter_drag_refresh_and_editor(agenda, authenticated_client, monkeypatch, tmp_path, width):
    from urllib.parse import urlparse
    from modules.hfl_corpus import corpus, router
    playwright = pytest.importorskip('playwright.sync_api')
    (tmp_path/'2026-09-18.md').write_text('## 2026-09-18 09:00\nMoment: Activity\nSource: notes\n',encoding='utf-8')
    monkeypatch.setattr(corpus,'resolve_corpus_root',lambda:tmp_path)
    monkeypatch.setattr(router,'corpus_index',corpus.CorpusIndex())
    item=agenda.create(payload(title='Follow-up browser check'),actor='test')[0]
    with playwright.sync_playwright() as driver:
        browser=driver.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':width,'height':1000})
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        def route(request_route):
            request=request_route.request
            url=urlparse(request.url)
            if url.hostname!='followups.test':
                request_route.abort();return
            response=authenticated_client.request(request.method,url.path+('?' + url.query if url.query else ''),content=request.post_data,
                headers={key:value for key,value in request.headers.items() if key.lower() in {'content-type','x-csrf-token'}})
            request_route.fulfill(status=response.status_code,body=response.content,headers={'content-type':response.headers.get('content-type','text/html')})
        page.route('**/*',route)
        page.goto('https://followups.test/hfl-corpus?source=notes')
        page.locator('.corpus-tools > summary').click()
        assert page.locator('.corpus-tools .tools-caret').is_visible()
        assert page.locator('[data-followups-open]').evaluate("el => getComputedStyle(el).backgroundColor") == 'rgba(0, 0, 0, 0)'
        page.locator('summary[aria-label="Profile menu"]').click()
        assert not page.locator('.corpus-tools').evaluate('el => el.open')
        assert page.locator('nav[aria-label="Profile menu"]').evaluate("el => {const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}")
        page.locator('summary[aria-label="Profile menu"]').click()
        page.locator('.corpus-tools > summary').click()
        page.locator('[data-followups-open]').click()
        board=page.locator('#followups-board')
        def drag_card(card, target, *, top=False):
            handle=card.locator('.action-drag-handle')
            handle.scroll_into_view_if_needed()
            start=handle.bounding_box()
            target.scroll_into_view_if_needed()
            end=target.bounding_box()
            page.mouse.move(start['x']+start['width']/2,start['y']+start['height']/2)
            page.mouse.down()
            page.mouse.move(start['x']+start['width']/2+8,start['y']+start['height']/2,steps=3)
            page.wait_for_timeout(80)
            page.mouse.move(end['x']+end['width']/2,end['y']+(12 if top else end['height']/2),steps=15)
            page.wait_for_timeout(350)
            page.mouse.up()
        playwright.expect(board.locator('[data-board-status]')).to_contain_text('0 actions')
        board.locator('.board-workspace-filter > summary').click()
        board.locator('.workspace-view-picker > summary').click()
        board.get_by_role('button',name='All activity',exact=True).click()
        board.locator('.board-workspace-filter > summary').click()
        playwright.expect(board.locator('[data-board-status]')).to_contain_text('1 action')
        card=board.locator('[data-followup-id]')
        playwright.expect(card.locator('.action-source')).to_have_text('manual-entry')
        playwright.expect(card.locator('.action-evidence-link')).to_have_count(0)
        assert card.locator('details[open]').count()==0
        if width < 600:
            card.get_by_role('button', name='Edit', exact=True).click()
            page.locator('#followup-form [name=status]').select_option('active')
            page.locator('#followup-form [type=submit]').click()
            playwright.expect(page.locator('#followup-form .editor-save-status')).to_have_text('Saved')
            page.locator('#followup-form [data-agenda-close]').first.click()
        else:
            drag_card(card,board.locator('[data-status=active].followups-lane'))
        playwright.expect(board.locator('[data-status=active].followups-lane [data-followup-id]')).to_have_count(1)
        updated=agenda.get(item['id'])
        assert updated['status']=='active'
        agenda.update(item['id'],{'version':updated['version'],'status':'in_progress'},actor='agent:test')
        playwright.expect(board.locator('[data-status=in_progress].followups-lane [data-followup-id]')).to_have_count(1,timeout=12000)
        board.get_by_role('button',name='Edit',exact=True).click()
        playwright.expect(page.locator('#followup-editor')).to_be_visible()
        page.locator('#followup-editor [data-agenda-close]').first.click()
        playwright.expect(board).to_be_visible()
        result_button=board.locator('.action-results-button')
        assert result_button.bounding_box()['width'] >= board.locator('.agenda-card-actions').bounding_box()['width']-2
        if width==1440:
            page.screenshot(path=str(tmp_path/'followups-board.png'))
            context_box=board.locator('[data-board-context]').bounding_box()
            toggle_box=board.locator('.board-workspace-filter > summary').bounding_box()
            assert abs((context_box['y']+context_box['height']/2)-(toggle_box['y']+toggle_box['height']/2)) < 3
        current=agenda.get(item['id'])
        agenda.update(item['id'],{'version':current['version'],'status':'done','completion_note':'## Saved report\n\n| Release | Bugs |\n| --- | --- |\n| R1 | **12** |'},actor='agent:external')
        result_button.click()
        results=page.locator('.agent-bridge-dialog')
        playwright.expect(results.locator('.markdown-body table')).to_have_count(1)
        playwright.expect(results).to_contain_text('Saved action outcome')
        playwright.expect(results.get_by_role('button',name='Run now')).to_be_disabled()
        results.get_by_role('button',name='Close agent results').click()
        board.get_by_role('button',name='History',exact=True).click()
        playwright.expect(page.locator('#followup-history .markdown-body table')).to_have_count(1)
        page.locator('#followup-history-close').click()
        first = agenda.create(payload(title='First ordered card', checklists=[{'id':'long-list','title':'Checklist','cover':True,
            'items':[{'id':str(index),'text':f'Task {index + 1}','done':False} for index in range(12)]}]),actor='test')[0]
        second = agenda.create(payload(title='Second ordered card'),actor='test')[0]
        board.locator('[data-board-refresh]').click()
        lane = board.locator('.followups-lane[data-status=open]')
        playwright.expect(lane.locator('[data-followup-id]')).to_have_count(2)
        first_card = lane.locator(f'[data-followup-id="{first["id"]}"]')
        second_card = lane.locator(f'[data-followup-id="{second["id"]}"]')
        playwright.expect(first_card.locator('.checklist-card-cover input')).to_have_count(12)
        playwright.expect(first_card.get_by_role('button',name='See full list')).to_have_count(0)
        if width == 1440:
            drag_card(second_card,first_card,top=True)
        else:
            second_card.focus()
            second_card.press('Alt+ArrowUp')
        playwright.expect(lane.locator('[data-followup-id]').first).to_have_attribute('data-followup-id',second['id'])
        playwright.expect(board.locator('[data-board-status]')).to_contain_text('3 actions')
        assert agenda.board_order()[second['id']] < agenda.board_order()[first['id']]
        board.locator('[data-board-refresh]').click()
        playwright.expect(lane.locator('[data-followup-id]').first).to_have_attribute('data-followup-id',second['id'])
        # A new page must recover the server order, not a DOM/local-storage order.
        page.reload()
        assert '/hfl-corpus/actions' in page.url
        playwright.expect(board.locator('[data-board-context]')).to_have_text('All activity')
        playwright.expect(lane.locator('[data-followup-id]').first).to_have_attribute('data-followup-id',second['id'])
        assert not errors
        browser.close()


def test_board_order_preserves_filtered_cards_and_rejects_stale_moves(agenda, authenticated_client):
    rows = [agenda.create(payload(title=title),actor='test')[0] for title in ['A','Hidden','B']]
    url='/hfl-corpus/timeline/items/order'
    order=lambda values: {'status':'open','items':[{'id':item['id'],'version':item['version']} for item in values]}
    response=authenticated_client.put(url,json=order([rows[2],rows[0]]))
    assert response.status_code==200,response.text
    positions=agenda.board_order()
    assert [positions[row['id']] for row in rows]==[2,1,0]
    assert all(agenda.get(row['id'])['version']==1 for row in rows)
    assert all(len(agenda.history(row['id']))==1 for row in rows)
    listed=authenticated_client.get('/hfl-corpus/timeline/items').json()['items']
    assert all(item['board_position']==positions[item['id']] for item in listed)
    agenda.update(rows[0]['id'],{'version':1,'status':'active'},actor='test')
    assert authenticated_client.put(url,json=order(rows)).status_code==409
    assert agenda.board_order()==positions
    assert authenticated_client.put(url,json=order([rows[2],rows[2]])).status_code==400
