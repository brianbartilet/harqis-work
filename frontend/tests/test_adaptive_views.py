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


def test_scope_api_and_remote_parity(authenticated_client, workspace_corpus):
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
    assert client.put('/hfl-corpus/view-preferences',headers=headers,json=state).status_code == 409
    assert client.put('/hfl-corpus/view-preferences',headers=headers,json={**state,'timezone':'nonsense'}).status_code == 422
    restored = client.get('/hfl-corpus',follow_redirects=False)
    params = parse_qs(urlparse(restored.headers['location']).query)
    assert params['views'][0].split(',') == state['manual']
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


@pytest.mark.parametrize('width',[390,1440])
def test_adaptive_browser(authenticated_client, workspace_corpus, tmp_path, width):
    playwright=pytest.importorskip('playwright.sync_api')
    headers, first, second=make_views(authenticated_client)
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
                response=authenticated_client.request(req.method,req.url.replace('http://adaptive.test',''),content=req.post_data,
                    headers={k:v for k,v in req.headers.items() if k in {'content-type','x-csrf-token'}},follow_redirects=True)
                route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-encoding','content-length'}})
            page.route('http://adaptive.test/**',route_request)
            page.goto('http://adaptive.test/hfl-corpus?reset=1')
            page.locator('[data-workspace-menu] summary').click()
            page.locator('[data-select-views]').click()
            for view in [first,second]: page.locator('[data-multi-options] input[value="'+view['id']+'"]').check()
            page.locator('[data-multi-form] button[type="submit"]').click()
            page.wait_for_function("document.querySelector('[data-active-view-name]').textContent.includes('+1')")
            assert '2 matching entries' in page.locator('[data-corpus-results]').inner_text()
            assert page.locator('[data-dynamic-badge]').inner_text()=='Dynamic off'
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('[data-workspace-menu] summary').click()
            page.locator('[data-workspace-action="edit"]').click()
            page.select_option('[data-edit-target]',first['id'])
            page.locator('[data-add-block]').click()
            assert page.locator('.workspace-day-options input:checked').count()==5
            page.screenshot(path=str(tmp_path/f'adaptive-edit-{width}.png'),full_page=True)
            page.locator('[data-workspace-confirm]').click()
            page.wait_for_function("!document.querySelector('[data-workspace-dialog]').open")
            updated=authenticated_client.get('/hfl-corpus/workspace-views').json()
            assert next(v for v in updated['views'] if v['id']==first['id'])['schedule'][0]['start']=='09:00'
            page.locator('[data-dynamic-toggle]').check()
            page.wait_for_function("document.querySelector('[data-dynamic-badge]').textContent==='Dynamic on'")
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(tmp_path/f'adaptive-{width}.png'),full_page=True)
            assert not errors,errors
        finally: browser.close()
