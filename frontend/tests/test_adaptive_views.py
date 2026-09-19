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
    assert active('2026-09-21T13:59:00+00:00') == ['fallback']
    assert active('2026-09-21T14:00:00+00:00') == ['night']
    assert active('2026-09-21T17:00:00+00:00') == ['night','early']
    assert active('2026-09-21T18:00:00+00:00') == ['early']
    assert active('2026-09-21T19:00:00+00:00') == ['fallback']
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
                entry = page.locator('.corpus-create-entry').bounding_box()
                action = page.locator('[data-create-action-open]').bounding_box()
                views = page.locator('[data-workspace-menu] > summary').bounding_box()
                assert abs(entry['y'] - action['y']) < 2
                assert views['y'] >= action['y'] + action['height']
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
            page.locator('[data-create-action-open]').click()
            assert not triage.evaluate('(el) => el.open')
            page.keyboard.press('Escape')

            page.locator('[data-workspace-menu] summary').click()
            assert page.locator('[data-dynamic-toggle]').is_disabled()
            assert 'Add a time block' in page.locator('[data-dynamic-hint]').inner_text()
            assert page.locator('[data-dynamic-toggle]').get_attribute('role') == 'switch'
            page.locator('[data-select-views]').click()
            for view in [first,second]: page.locator('[data-multi-options] input[value="'+view['id']+'"]').check()
            page.locator('[data-multi-form] button[type="submit"]').click()
            page.wait_for_function("document.querySelector('[data-active-view-name]').textContent.includes('+1')")
            assert '2 matching entries' in page.locator('[data-corpus-results]').inner_text()
            assert page.locator('[data-dynamic-badge]').inner_text()=='Dynamic off'
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('[data-workspace-menu] summary').click()
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

            page.locator('[data-add-block]').click()
            assert page.locator('.workspace-day-options input:checked').count()==5
            page.screenshot(path=str(tmp_path/f'adaptive-edit-{width}.png'),full_page=True)
            page.locator('[data-workspace-confirm]').click()
            page.wait_for_function("!document.querySelector('[data-workspace-dialog]').open")
            updated=authenticated_client.get('/hfl-corpus/workspace-views').json()
            assert next(v for v in updated['views'] if v['id']==first['id'])['schedule'][0]['start']=='09:00'
            page.wait_for_function("() => JSON.parse(document.querySelector('[data-workspace-data]').textContent).views.some(v => v.name === 'Work' && v.schedule.length === 1) && document.querySelector('[data-dynamic-toggle]').onchange !== null")
            page.locator('[data-workspace-menu]').evaluate('(el) => el.open = true')
            page.locator('[data-dynamic-toggle]').check()
            page.wait_for_function("document.querySelector('[data-dynamic-badge]').textContent==='Dynamic on'")
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(tmp_path/f'adaptive-{width}.png'),full_page=True)
            # Block transition during dialogs, then preserve the loaded results on error.
            page.locator('[data-workspace-menu]').evaluate('(el) => el.open = true')
            page.locator('[data-workspace-help-open]').click()
            scheduled[:] = [first['id']]
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            assert '+1' in page.locator('[data-active-view-name]').inner_text()
            page.locator('#workspace-help [data-workspace-help-close]').last.click()
            page.locator('[data-workspace-menu]').evaluate('(el) => el.open = false')
            failed[0] = True
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            page.wait_for_function("document.querySelector('[data-adaptive-status]').textContent.includes('retry')")
            assert '+1' in page.locator('[data-active-view-name]').inner_text()
            assert '2 matching entries' in page.locator('[data-corpus-results]').inner_text()
            failed[0] = False
            page.locator('[data-adaptive-status] button').click()
            page.wait_for_function("document.querySelector('[data-active-view-name]').textContent==='Work'")
            assert '1 matching entries' in page.locator('[data-corpus-results]').inner_text()
            page.wait_for_function("document.querySelector('[data-activity-body]').classList.contains('workspace-arrive')")
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
