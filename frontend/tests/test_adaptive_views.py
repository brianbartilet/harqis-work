import json
from dataclasses import replace
from datetime import datetime, timezone, date
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import pytest
from test_corpus_workspaces import workspace_corpus
from test_corpus_share_handoff import handoff_corpus
from modules.hfl_corpus import workspace_views
from modules.hfl_corpus.view_scope import ViewScope, filter_scope
from modules.hfl_shares.security import make_csrf_token


def test_memory_count_includes_all_years_and_undated_entries(authenticated_client, workspace_corpus, monkeypatch):
    from urllib.parse import urlencode
    import modules.hfl_corpus.router as routes
    current = date.today().year
    old = replace(workspace_corpus, relative_path=f'{current-1}-01-01.md',
                  entries=(workspace_corpus.entries[0],), entry_count=1)
    undated = replace(workspace_corpus, relative_path='undated.md',
                      entries=(replace(workspace_corpus.entries[0], header='Undated'),), entry_count=1)
    monkeypatch.setattr(routes.corpus_index, 'documents', lambda: (workspace_corpus, old, undated))
    scope = json.dumps({'any': [{'source': 'git,notes'}]})
    url = '/hfl-corpus?' + urlencode({'scope': scope, 'activity_year': current})
    response = authenticated_client.get(url)
    assert '4 entries</h2>' in response.text
    api = authenticated_client.get('/api/hfl/documents', params={'scope': scope, 'compact': 'true', 'page_size': 20},
                                   headers={'Authorization': 'Bearer frontend-test-hfl-api-token'})
    assert api.json()['total_entries'] == 4
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as engine:
        options = {'headless': True}
        if not Path(engine.chromium.executable_path).exists():
            options['channel'] = 'msedge'
        browser = engine.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={'width': 1440, 'height': 900}, reduced_motion='reduce')
            def route_request(route):
                req = route.request
                result = authenticated_client.request(req.method, req.url.replace('http://localhost', ''),
                                                      follow_redirects=True)
                route.fulfill(status=result.status_code, body=result.content,
                              headers={k: v for k, v in result.headers.items()
                                       if k.lower() not in {'content-encoding', 'content-length'}})
            page.route('http://localhost/**', route_request)
            page.goto('http://localhost' + url)
            title = page.locator('#activity-title')
            playwright.expect(title).to_have_text('4 entries')
            for year in [current-1, current-2, current]:
                page.locator(f'[data-activity-year-option="{year}"]').click()
                playwright.expect(page.locator('[data-activity-year]')).to_have_value(str(year))
                playwright.expect(title).to_have_text('4 entries')
        finally:
            browser.close()


def make_views(client):
    headers = {'X-CSRF-Token':make_csrf_token('frontend-test-user')}
    first = client.post('/hfl-corpus/workspace-views', headers=headers, json={'name':'Work','state':{'source':'git','q':'#work'}}).json()
    second = client.post('/hfl-corpus/workspace-views', headers=headers, json={'name':'Personal','state':{'source':'browsing','q':'#personal'}}).json()
    return headers, first, second


def test_union_preserves_pairs_dates_and_duplicates(authenticated_client, workspace_corpus):
    from modules.hfl_corpus.corpus import activity_counts
    scope = ViewScope.model_validate({'any':[{'source':'git','q':'#work'}, {'source':'browsing','q':'#personal'}, {'source':'git'}]})
    documents = filter_scope((workspace_corpus,), scope)
    assert [e.source for e in documents[0].entries] == ['git','browsing']
    assert documents[0].matching_entry_count == 2
    assert sum(activity_counts(documents, year=date.today().year).values()) == 2
    # Additional filters narrow the union, never cross-match source/tag pairs.
    scope.all.q = '#work'
    assert [e.source for e in filter_scope((workspace_corpus,), scope)[0].entries] == ['git']
    scope.all.date_from = '2999-01-01'
    assert not filter_scope((workspace_corpus,), scope)
    with pytest.raises(ValueError):
        ViewScope.model_validate({'any':[{'date_from':'2026-10-01','date_to':'2026-09-01'}]})


def test_scope_api_and_remote_parity(authenticated_client, workspace_corpus, monkeypatch):
    from modules.hfl_corpus.remote import RemoteCorpusClient
    scope = json.dumps({'any':[{'source':'git','q':'#work'}, {'source':'browsing','q':'#personal'}]})
    headers = {'Authorization':'Bearer frontend-test-hfl-api-token'}
    client = authenticated_client
    response = client.get('/api/hfl/documents', params={'scope':scope,'compact':'true'}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data['results'][0]['matching_entry_count'] == 2
    assert sum(data['activity']['counts'].values()) == 2
    matches = client.get('/api/hfl/matches/today.md', params={'scope':scope}, headers=headers).json()
    assert [e['source'] for e in matches['entries']] == ['git','browsing']
    narrowed = client.get('/api/hfl/documents', params={'scope':scope,'q':'#work','compact':'true'}, headers=headers).json()
    assert narrowed['results'][0]['matching_entry_count'] == 1
    assert sum(narrowed['activity']['counts'].values()) == 1
    page = client.get('/hfl-corpus', params={'scope':scope})
    assert page.status_code == 200 and '2 matching entries' in page.text
    assert client.get('/hfl-corpus', params={'scope':'bad'}).status_code == 422
    remote = RemoteCorpusClient('http://canonical.test', 'unused')
    monkeypatch.setattr(remote, '_get', lambda path, params: client.get('/api/hfl'+path,params=params,headers=headers))
    result = remote.index(params={'scope':scope})
    assert result['results'][0].matching_entry_count == 2
    assert sum(result['activity']['counts'].values()) == 2
    assert len(remote.matches('today.md',scope=scope,query='')['entries']) == 2



def test_schedule_boundaries_overlap_and_timezone():
    prefs = {'dynamic':True, 'manual':['fallback'], 'timezone':'Asia/Singapore'}
    views = [{'id':'night','schedule':[{'days':[0],'start':'22:00','end':'02:00'}]},
             {'id':'early','schedule':[{'days':[1],'start':'01:00','end':'03:00'}]}]
    # Monday night continues into Tuesday, times are Singapore local.
    def active(utc): return workspace_views.active_views(views,prefs,datetime.fromisoformat(utc))
    assert active('2026-09-21T13:59:00+00:00') == []
    assert active('2026-09-21T14:00:00+00:00') == ['night']
    assert active('2026-09-21T17:00:00+00:00') == ['night','early']
    assert active('2026-09-21T18:00:00+00:00') == ['early']
    assert active('2026-09-21T19:00:00+00:00') == []
    prefs['dynamic'] = False
    assert active('2026-09-21T17:00:00+00:00') == ['fallback']
    prefs.update(dynamic=True, timezone='America/New_York')
    views = [{'id':'repeat','schedule':[{'days':[6],'start':'01:00','end':'02:00'}]}]
    assert active('2026-11-01T05:30:00+00:00') == ['repeat']
    assert active('2026-11-01T06:30:00+00:00') == ['repeat']


def test_preferences_schedule_persistence_and_conflicts(authenticated_client, workspace_corpus):
    client=authenticated_client
    headers, first, second = make_views(client)
    state = {'manual':[first['id'],second['id']], 'dynamic':False,'timezone':'Asia/Singapore','revision':0}
    assert client.put('/hfl-corpus/view-preferences',json=state).status_code == 403
    result = client.put('/hfl-corpus/view-preferences',headers=headers,json=state)
    assert result.status_code == 200
    assert result.json()['active'] == state['manual']
    denied = client.put('/hfl-corpus/view-preferences',headers=headers,json={**state,'revision':1,'dynamic':True})
    assert denied.status_code == 422 and 'time block' in denied.json()['detail']
    assert client.get('/hfl-corpus/workspace-views').json()['preferences']['dynamic'] is False
    assert client.put('/hfl-corpus/view-preferences',headers=headers,json=state).status_code == 409
    assert client.put('/hfl-corpus/view-preferences',headers=headers,json={**state,'timezone':'nonsense'}).status_code == 422
    restored = client.get('/hfl-corpus',follow_redirects=False)
    params = parse_qs(urlparse(restored.headers['location']).query)
    assert set(params['views'][0].split(',')) == set(state['manual'])
    assert len(json.loads(params['scope'][0])['any']) == 2
    schedule = [{'days':[0,1,2,3,4], 'start':'09:00','end':'17:00'}]
    updated=client.put('/hfl-corpus/workspace-views/'+first['id'],headers=headers,json={'name':first['name'],'state':first['state'],'revision':first['revision'],'schedule':schedule}).json()
    assert updated['schedule'] == schedule
    assert client.delete('/hfl-corpus/workspace-views/'+first['id']+'?revision='+str(updated['revision']),headers=headers).status_code==200
    assert client.get('/hfl-corpus/workspace-views').json()['preferences']['manual'] == [second['id']]


def test_aggregated_sharing_preview_and_recipe_roundtrip(authenticated_client, handoff_corpus):
    import html, re
    from modules.hfl_shares.models import ShareConfiguration, ALL_SOURCES
    from modules.hfl_shares.scope import build_snapshot
    scope={'any':[{'source':'notes','q':'#work ignored text'}, {'source':'notes','q':'#work','date_field':'entry','date_from':'2020-01-01','date_to':'2020-01-01'}]}
    data={'csrf':make_csrf_token('frontend-test-user'),'state':'{}','scope':json.dumps(scope)}
    preview=authenticated_client.post('/sharing/from-corpus?mode=preview',data=data)
    assert preview.status_code==200
    assert preview.text.count('Plan next week') >= 1
    assert 'data-test-question' not in preview.text
    draft=authenticated_client.post('/sharing/from-corpus',data=data)
    assert draft.status_code==200
    assert 'Combined Activity Views scope' in draft.text
    encoded=html.unescape(re.search(r'name="corpus_scope" value="([^"]+)"',draft.text)[1])
    assert 'ignored text' not in encoded
    cfg=ShareConfiguration(id='',name='Combined',recipient='Owner',sources=(ALL_SOURCES,),corpus_scope=encoded)
    entries=build_snapshot(cfg,(handoff_corpus,)).entries
    assert len(entries)==1
    assert ShareConfiguration(**cfg.to_record()).corpus_scope==encoded


@pytest.mark.parametrize('width',[320,390,1440])
def test_adaptive_browser(authenticated_client, workspace_corpus, tmp_path, width, monkeypatch):
    playwright=pytest.importorskip('playwright.sync_api')
    headers, first, second=make_views(authenticated_client)
    scheduled = [first['id'], second['id']]
    monkeypatch.setattr(workspace_views, 'active_views', lambda views, prefs: scheduled[:] if prefs['dynamic'] else prefs['manual'])
    failed = [False]
    import modules.hfl_shares.router as shares
    monkeypatch.setattr(shares, '_sharing_documents', lambda *a, **k: (workspace_corpus,))
    monkeypatch.setattr(shares, '_sharing_catalog', lambda: ((workspace_corpus,), ('git','browsing','notes'), (('work',2),('personal',1))))
    with playwright.sync_playwright() as engine:
        options={'headless':True}
        if not Path(engine.chromium.executable_path).exists(): options['channel']='msedge'
        browser=engine.chromium.launch(**options)
        try:
            page=browser.new_page(viewport={'width':width,'height':900})
            errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            def route_request(route):
                req=route.request
                if failed[0] and '/hfl-corpus?' in req.url and 'scope=' in req.url:
                    route.fulfill(status=503, body='Temporary failure'); return
                response=authenticated_client.request(req.method,req.url.replace('http://localhost',''),content=req.post_data,
                    headers={k:v for k,v in req.headers.items() if k in {'content-type','x-csrf-token'}},follow_redirects=True)
                route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-encoding','content-length'}})
            page.route('http://localhost/**',route_request)
            page.goto('http://localhost/hfl-corpus?reset=1')
            if width < 640:
                create = page.locator('.corpus-create-menu > summary').bounding_box()
                explore = page.locator('.corpus-tools > summary').bounding_box()
                views = page.locator('[data-workspace-menu] > summary').bounding_box()
                assert abs(explore['y'] - views['y']) < 2
                assert abs(explore['width'] - views['width']) < 2
                assert abs(create['x'] - explore['x']) < 2
                assert abs(create['x']+create['width'] - views['x']-views['width']) < 2
                assert views['y'] >= create['y'] + create['height']
            page.screenshot(path=str(tmp_path/f'header-menus-{width}.png'))
            page.locator('.corpus-create-menu > summary').click()
            page.locator('[data-create-action-open]').click()
            assert not errors, errors
            playwright.expect(page.locator('#followup-editor')).to_be_visible()
            assert page.locator('#followup-form [name="due_date"]').input_value() == ''
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(tmp_path/f'create-actionable-{width}.png'),full_page=True)
            triage = page.locator('#followup-editor .action-triage')
            assert not triage.evaluate('(el) => el.open')
            triage.locator('summary').click()
            matrix = page.locator('#followup-form [name="matrix"]')
            confidence = page.locator('#followup-form [name="matrix_confidence"]')
            assert abs(matrix.bounding_box()['y'] - confidence.bounding_box()['y']) < 2
            assert page.locator('#followup-editor').evaluate('(el) => el.scrollWidth <= el.clientWidth')
            page.screenshot(path=str(tmp_path/f'action-triage-{width}.png'),full_page=True)
            page.keyboard.press('Escape')
            playwright.expect(page.locator('#followup-editor')).not_to_be_visible()
            page.locator('.corpus-create-menu > summary').click()
            page.locator('[data-create-action-open]').click()
            assert not triage.evaluate('(el) => el.open')
            page.keyboard.press('Escape')

            page.locator('[data-workspace-menu] > summary').click()
            assert page.locator('[data-dynamic-toggle]').is_disabled()
            assert 'Add a time block' in page.locator('[data-dynamic-hint]').inner_text()
            assert page.locator('[data-dynamic-toggle]').get_attribute('role') == 'switch'
            page.locator('[data-view-picker] > summary').click()
            for view in [first,second]: page.locator('[data-view-choices] input[value="'+view['id']+'"]').check()
            assert page.locator('[data-active-view-name]').inner_text() == 'All activity'
            assert page.locator('[data-view-all] input, [data-view-all] .view-color-dot').count() == 0
            page.screenshot(path=str(tmp_path/f'view-picker-{width}.png'),full_page=True)
            if width == 320:
                page.keyboard.press('Escape')
            elif width == 390:
                page.locator('.workspace-focus-label').click()
            else:
                page.locator('[data-view-picker] > summary').click()
            page.wait_for_function("document.querySelector('[data-active-view-name]').textContent.includes('Work') && document.querySelector('[data-active-view-name]').textContent.includes('Personal')")
            assert '2 matching entries' in page.locator('[data-corpus-results]').inner_text()
            assert page.locator('[data-dynamic-badge]').inner_text()=='Dynamic OFF'
            assert page.locator('[data-source-option][value="git"]').is_checked()
            assert page.locator('[data-source-option][value="browsing"]').is_checked()
            assert page.locator('[data-source-caption]').inner_text() == '2 selected from views'
            assert page.locator('#q').get_attribute('placeholder') == 'Search within selected views'
            page.locator('[data-corpus-search]').click()
            page.wait_for_load_state()
            assert '2 matching entries' in page.locator('[data-corpus-results]').inner_text()
            assert json.loads(parse_qs(urlparse(page.url).query)['scope'][0])['all']['source'] == ''
            page.locator('#q').fill('temporary narrowing')
            page.locator('[data-workspace-reset]').first.click()
            playwright.expect(page.locator('#q')).to_have_value('')
            playwright.expect(page.locator('[data-active-view-name]')).to_contain_text('Work')
            playwright.expect(page.locator('[data-active-view-name]')).to_contain_text('Personal')
            assert '2 matching entries' in page.locator('[data-corpus-results]').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('[data-workspace-menu] > summary').click()
            assert page.locator('[data-workspace-action="save"]').is_disabled()
            assert page.locator('[data-workspace-action="remove"]').is_disabled()
            assert page.locator('[data-workspace-action="new"]').is_enabled()
            assert page.locator('[data-workspace-save-hint]').inner_text() == 'Select one view to save changes.'
            page.locator('[data-corpus-share-preview]').click()
            preview = page.locator('[data-corpus-share-dialog]')
            playwright.expect(preview.locator('[data-preview-ready]')).to_be_visible()
            assert preview.locator('.stat').first.inner_text().startswith('2')
            assert preview.locator('[data-test-question]').count() == 0
            page.screenshot(path=str(tmp_path/f'adaptive-sharing-{width}.png'),full_page=True)
            page.locator('[data-corpus-share-close]').click()
            page.locator('[data-workspace-action="edit"]').click()
            page.select_option('[data-edit-target]',first['id'])
            assert page.locator('[data-applied-filters]').get_attribute('open') is None
            assert page.locator('[data-assigned-schedules]').get_attribute('open') is not None
            assert page.locator('[data-assigned-schedules]').bounding_box()['y'] < page.locator('[data-applied-filters]').bounding_box()['y']
            assert page.locator('[data-edit-target]').bounding_box()['y'] < page.locator('#workspace-name').bounding_box()['y']
            page.locator('[data-applied-filters] > summary').click()
            page.locator('[data-edit-sources] > summary').click()
            page.locator('[data-edit-source-options] input[value="notes"]').check()
            assert set(page.locator('[data-edit-filter="source"]').input_value().split(',')) == {'git','notes'}
            page.screenshot(path=str(tmp_path/f'editor-sources-{width}.png'),full_page=True)
            page.locator('[data-edit-source-options] input[value="notes"]').uncheck()
            page.keyboard.press('Escape')
            assert page.locator('[data-workspace-dialog]').is_visible()
            assert page.locator('[data-edit-sources]').get_attribute('open') is None
            page.locator('[data-edit-sources] > summary').click()
            page.locator('#workspace-name').click()
            assert page.locator('[data-edit-sources]').get_attribute('open') is None
            page.locator('[data-applied-filters] > summary').click()

            page.locator('[data-view-colors] button').nth(5).click()
            page.locator('[data-add-block]').click()
            assert page.locator('.workspace-day-options input:checked').count()==5
            page.screenshot(path=str(tmp_path/f'adaptive-edit-{width}.png'),full_page=True)
            page.locator('[data-workspace-confirm]').click()
            page.wait_for_function("!document.querySelector('[data-workspace-dialog]').open")
            updated=authenticated_client.get('/hfl-corpus/workspace-views').json()
            assert next(v for v in updated['views'] if v['id']==first['id'])['schedule'][0]['start']=='09:00'
            page.wait_for_function("() => JSON.parse(document.querySelector('[data-workspace-data]').textContent).views.some(v => v.name === 'Work' && v.schedule.length === 1) && document.querySelector('[data-dynamic-toggle]').onchange !== null")
            page.locator('[data-workspace-menu]').evaluate('(el) => el.open = true')
            # Another view overlaps Monday and crosses the Sunday/Monday boundary.
            overlap = authenticated_client.put('/hfl-corpus/workspace-views/'+second['id'], headers=headers,
                json={'name':second['name'], 'state':second['state'], 'revision':second['revision'],
                      'schedule':[{'days':[0], 'start':'10:00','end':'11:00'}, {'days':[6], 'start':'22:00','end':'02:00'}, {'days':[1], 'start':'09:00','end':'17:00'}]})
            assert overlap.status_code == 200
            page.locator('[data-visualize-open]').click()
            calendar = page.locator('#view-visualizer')
            playwright.expect(calendar.locator('.visualizer-block')).to_have_count(9)
            assert 'Dynamic OFF' in calendar.locator('[data-visualize-status]').inner_text()
            assert 'Asia/Singapore' in calendar.locator('[data-visualize-zone]').inner_text()
            assert calendar.locator('.visualizer-day-heading').first.inner_text().startswith('Mon')
            assert calendar.locator('.visualizer-now').count() == 1
            assert calendar.evaluate('(el) => el.scrollWidth <= el.clientWidth')
            monday = calendar.locator('.visualizer-day').first
            overlapping = monday.locator('.visualizer-block').filter(has_text='10:00–11:00')
            work = monday.locator('.visualizer-block').filter(has_text='Work')
            assert overlapping.bounding_box()['x'] > work.bounding_box()['x']
            assert overlapping.evaluate('(el) => Number(el.style.zIndex)') > work.evaluate('(el) => Number(el.style.zIndex)')
            label = work.locator('.visualizer-block-label').bounding_box()
            assert 0 <= label['y'] - work.bounding_box()['y'] <= 10
            tuesday = calendar.locator('.visualizer-day').nth(1)
            peers = tuesday.locator('.visualizer-block')
            assert peers.count() == 2
            first_box, second_box = peers.nth(0).bounding_box(), peers.nth(1).bounding_box()
            assert abs(first_box['width'] - second_box['width']) < 2
            assert first_box['x'] + first_box['width'] <= second_box['x']
            assert second_box['x'] + second_box['width'] <= tuesday.bounding_box()['x'] + tuesday.bounding_box()['width']
            if width >= 1000:
                toolbar = calendar.locator('.visualizer-toolbar')
                assert toolbar.bounding_box()['height'] < 70
            calendar.locator('.visualizer-scroll').evaluate('(el) => el.scrollTop = 8 * 48')

            assert monday.locator('.visualizer-block').filter(has_text='22:00–02:00').count() == 1
            assert calendar.locator('.visualizer-day').last.locator('.visualizer-block').filter(has_text='22:00–02:00').count() == 1
            page.screenshot(path=str(tmp_path/f'visualizer-week-{width}.png'),full_page=True)
            work.click()
            assert 'git' in calendar.locator('[data-visualize-detail]').inner_text()
            assert '#work' in calendar.locator('[data-visualize-detail]').inner_text()
            page.screenshot(path=str(tmp_path/f'visualizer-{width}.png'),full_page=True)
            calendar.get_by_role('button', name='Edit view', exact=True).click()
            playwright.expect(page.locator('[data-workspace-dialog]')).to_be_visible()
            assert page.locator('#workspace-name').input_value() == 'Work'
            assert page.locator('[data-view-colors] button').nth(5).get_attribute('aria-pressed') == 'true'
            page.locator('[data-workspace-cancel]').click()
            page.locator('[data-workspace-menu]').evaluate('(el) => el.open = true')
            page.locator('[data-dynamic-toggle]').check()
            page.wait_for_function("document.querySelector('[data-dynamic-badge]').textContent==='Dynamic ON'")
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(tmp_path/f'adaptive-{width}.png'),full_page=True)
            # Block transition during dialogs, then preserve the loaded results on error.
            page.locator('[data-workspace-menu]').evaluate('(el) => el.open = true')
            page.locator('[data-workspace-help-open]').click()
            scheduled[:] = [first['id']]
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            playwright.expect(page.locator('[data-active-view-name]')).to_contain_text('Personal')
            page.locator('#workspace-help [data-workspace-help-close]').last.click()
            page.locator('[data-workspace-menu]').evaluate('(el) => el.open = false')
            failed[0] = True
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            page.wait_for_function("document.querySelector('[data-adaptive-status]').textContent.includes('retry')")
            playwright.expect(page.locator('[data-active-view-name]')).to_contain_text('Personal')
            assert '2 matching entries' in page.locator('[data-corpus-results]').inner_text()
            failed[0] = False
            page.locator('[data-adaptive-status] button').click()
            page.wait_for_function("document.querySelector('[data-active-view-name]').textContent==='Work'")
            assert page.locator('[data-workspace-action="save"]').is_enabled()
            assert page.locator('[data-workspace-save-hint]').is_hidden()
            assert '1 matching entries' in page.locator('[data-corpus-results]').inner_text()
            page.locator('.corpus-tools > summary').click()
            page.locator('[data-followups-open]').click()
            playwright.expect(page.locator('#followups-board')).to_be_visible()
            playwright.expect(page.locator('[data-board-context]')).to_contain_text('Work')
            page.wait_for_function("document.querySelector('[data-activity-body]').classList.contains('workspace-arrive')")
            # A schedule gap loads all activity without disabling Dynamic mode.
            scheduled[:] = []
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            page.wait_for_function("document.querySelector('[data-active-view-name]').textContent === 'All activity'")
            assert page.locator('[data-dynamic-badge]').inner_text() == 'Dynamic ON'
            assert '3 entries' in page.locator('[data-corpus-results]').inner_text()
            assert json.loads(parse_qs(urlparse(page.url).query)['scope'][0])['any'] == []
            assert authenticated_client.get('/hfl-corpus/workspace-views').json()['preferences']['dynamic'] is True
            playwright.expect(page.locator('#followups-board')).to_be_visible()
            playwright.expect(page.locator('[data-board-context]')).to_contain_text('All activity')
            page.locator('[data-board-close]').click()
            page.locator('[data-workspace-menu]').evaluate('(el) => el.open = true')
            page.locator('[data-view-picker] > summary').click()
            page.locator('[data-view-all]').click()
            page.wait_for_function("document.querySelector('[data-dynamic-badge]').textContent === 'Dynamic OFF'")
            page.wait_for_function("document.querySelector('[data-active-view-name]').textContent === 'All activity'")
            assert json.loads(parse_qs(urlparse(page.url).query)['scope'][0])['any'] == []
            prefs = authenticated_client.get('/hfl-corpus/workspace-views').json()['preferences']
            assert prefs['manual'] == [] and prefs['dynamic'] is False
            import modules.hfl_corpus.router as corpus_routes
            from modules.hfl_corpus.remote import RemoteCorpusClient, RemoteCorpusError
            from types import SimpleNamespace
            def unavailable(**kwargs):
                raise RemoteCorpusError('Update the canonical corpus host to support combined views.')
            monkeypatch.setattr(corpus_routes, '_uses_remote_corpus', lambda: True)
            monkeypatch.setattr(RemoteCorpusClient, 'from_settings', staticmethod(lambda: SimpleNamespace(index=unavailable)))
            page.reload()
            playwright.expect(page.locator('[data-corpus-load-error]')).to_be_visible()
            page.get_by_role('button',name='Dismiss corpus error').click()
            playwright.expect(page.locator('[data-corpus-load-error]')).not_to_be_visible()
            assert not errors,errors
        finally: browser.close()


def test_view_colors_and_unscheduled_all_entries(authenticated_client, workspace_corpus):
    from modules.hfl_corpus.memory_pins import PIN_COLORS
    client = authenticated_client
    headers, first, second = make_views(client)
    assert first['color'] in PIN_COLORS
    assert first['color'] != second['color']
    response = client.put('/hfl-corpus/workspace-views/'+first['id'], headers=headers,
        json={'name':first['name'], 'state':first['state'], 'revision':first['revision'], 'color':PIN_COLORS[-1]})
    assert response.status_code == 200
    saved = response.json()
    assert saved['color'] == PIN_COLORS[-1]
    invalid = client.put('/hfl-corpus/workspace-views/'+first['id'], headers=headers,
        json={'name':first['name'], 'state':first['state'], 'revision':saved['revision'], 'color':'red'})
    assert invalid.status_code == 422
    kept = client.put('/hfl-corpus/workspace-views/'+first['id'], headers=headers,
        json={'name':first['name'], 'state':first['state'], 'revision':saved['revision']}).json()
    assert kept['color'] == PIN_COLORS[-1]
    snapshot = workspace_views.listing()
    assert snapshot['palette'] == list(PIN_COLORS)
    url = workspace_views.selection_url(snapshot, identities=[], dynamic=True)
    assert len(filter_scope((workspace_corpus,), ViewScope.model_validate_json(parse_qs(urlparse(url).query)['scope'][0]))[0].entries) == 3


def test_view_color_migration_preserves_existing_views(authenticated_client):
    from modules.hfl_corpus.graph_views import connection
    from modules.hfl_corpus.memory_pins import PIN_COLORS
    with connection() as db:
        db.execute('DROP TABLE IF EXISTS corpus_workspace_views')
        db.execute('CREATE TABLE corpus_workspace_views (id TEXT PRIMARY KEY, name TEXT, state TEXT, revision INTEGER)')
        db.execute('INSERT INTO corpus_workspace_views VALUES (?,?,?,?)', ('old','Existing','{}',4))
    first = workspace_views.listing()['views'][0]
    assert first['id'] == 'old' and first['revision'] == 4
    assert first['color'] in PIN_COLORS
    assert workspace_views.listing()['views'][0]['color'] == first['color']


@pytest.mark.parametrize('page_size', [20,50,100])
def test_scope_accepts_numeric_query_parameters(authenticated_client, workspace_corpus, page_size):
    scope = json.dumps({'any':[{'source':'git'}]})
    response = authenticated_client.get('/api/hfl/documents',
        params={'scope':scope, 'page_size':str(page_size), 'rolling':'7', 'compact':'true'},
        headers={'Authorization':'Bearer frontend-test-hfl-api-token'})
    assert response.status_code == 200, response.text
    assert response.json()['page_size'] == page_size
    assert response.json()['results'][0]['matching_entry_count'] == 1
    page = authenticated_client.get('/hfl-corpus', params={'scope':scope, 'page_size':str(page_size), 'rolling':'7'})
    assert page.status_code == 200
    invalid = authenticated_client.get('/hfl-corpus', params={'scope':scope, 'page_size':'21'})
    assert invalid.status_code == 422
