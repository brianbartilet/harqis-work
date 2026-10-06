"""Workspace boundaries and full-board visibility use the owner permission graph."""
import json
from uuid import uuid4

import pytest
from urllib.parse import urlencode

from test_hfl_ideas import ideas, payload, BASE
from test_hfl_boards import board_payload


def test_all_activity_defaults_are_not_a_filter():
    from modules.hfl_corpus.graph_workspace import active_context
    assert active_context('views=&q=&source=&rolling=0&workspace_revision=5') == ''
    assert active_context('views=work') == 'views=work'
    assert active_context('q=planning') == 'q=planning'


def test_board_navigation_inherits_shared_selection(authenticated_client):
    from modules.hfl_corpus import workspace_views
    work = workspace_views.save(workspace_views.WorkspaceWrite(name='Work', state={'source': 'git'}))
    response = authenticated_client.get('/hfl-corpus/graph?board=example', follow_redirects=False)
    assert response.status_code == 303
    assert 'board=example' in response.headers['location']
    assert 'workspace=' + work['id'] in response.headers['location']
    assert 'source=git' in response.headers['location']


def test_assignments_override_saved_filters_but_not_additional_filters(ideas, authenticated_client):
    from modules.hfl_corpus.entities import graph
    assigned = ideas.save_idea(payload(title='Assigned', workspace_ids=['work']), 'owner')
    other = ideas.save_idea(payload(title='Other'), 'owner')
    board = ideas.save_map(board_payload(workspace_ids=['work']))
    unassigned = ideas.save_map(board_payload(name='Unassigned'))
    scope = {'any': [{'source': 'git'}], 'all': {}}
    context = urlencode({'views': 'work', 'scope': json.dumps(scope)})
    ids = {n['id'] for n in graph(limit=0, context=context)['nodes']}
    assert 'idea:' + assigned['id'] in ids
    assert 'idea:' + other['id'] not in ids
    assert 'board:' + board['id'] in ids
    assert 'board:' + unassigned['id'] not in ids
    scope['all'] = {'q': 'not present'}
    narrowed = graph(limit=0, context=urlencode({'views': 'work', 'scope': json.dumps(scope)}))
    assert 'idea:' + assigned['id'] not in {n['id'] for n in narrowed['nodes']}
    assert 'board:' + unassigned['id'] in {n['id'] for n in graph(limit=0)['nodes']}


def test_board_retains_outside_members_and_marks_them(ideas, authenticated_client):
    inside = ideas.save_idea(payload(title='Inside', workspace_ids=['work']), 'owner')
    outside = ideas.save_idea(payload(title='Outside'), 'owner')
    board = ideas.save_map(board_payload(workspace_ids=['work'], members=['idea:'+inside['id'], 'idea:'+outside['id']]))
    scope = {'any': [{'source': 'git'}], 'all': {}}
    context = urlencode({'views': 'work', 'scope': json.dumps(scope)})
    response = authenticated_client.get(BASE+'/maps/'+board['id']+'/graph', params={'context': context})
    assert response.status_code == 200, response.text
    nodes = {n['id']: n for n in response.json()['nodes']}
    assert nodes['idea:'+inside['id']]['outside_workspace'] is False
    assert nodes['idea:'+outside['id']]['outside_workspace'] is True


def test_scope_never_includes_other_board_through_shared_goal(ideas, authenticated_client):
    from modules.hfl_corpus.entities import graph
    goal = ideas.save_goal({'request_id': str(uuid4()), 'title': 'Shared outcome'}, 'owner')
    first = ideas.save_map(board_payload(workspace_ids=['work'], goal_id=goal['id'], members=['goal:'+goal['id']]))
    second = ideas.save_map(board_payload(workspace_ids=['home'], goal_id=goal['id'], members=['goal:'+goal['id']]))
    result = graph(limit=0, context='views=work')
    ids = {n['id'] for n in result['nodes']}
    assert 'board:'+first['id'] in ids
    assert 'board:'+second['id'] not in ids
    assert 'goal:'+goal['id'] in ids
    assert all(e['source'] in ids and e['target'] in ids for e in result['edges'])


@pytest.mark.parametrize('width', [390, 1440])
def test_workspace_boards_and_global_entities_browser(ideas, authenticated_client, tmp_path, width):
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright, expect
    from modules.hfl_corpus import workspace_views
    work = workspace_views.save(workspace_views.WorkspaceWrite(name='Work', state={'source': 'git'}))
    first = ideas.save_idea(payload(title='Assigned member', workspace_ids=[work['id']]), 'owner')
    outside = ideas.save_idea(payload(title='Context member'), 'owner')
    board = ideas.save_map(board_payload(name='Work board', workspace_ids=[work['id']], members=['idea:'+first['id'], 'idea:'+outside['id']]))
    other = ideas.save_map(board_payload(name='Other board'))
    with sync_playwright() as engine:
        browser = engine.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def respond(route):
            req = route.request
            url = urlsplit(req.url)
            response = authenticated_client.request(req.method, url.path+('?' + url.query if url.query else ''), content=req.post_data,
                headers={k:v for k,v in req.headers.items() if k in {'content-type', 'x-csrf-token'}})
            route.fulfill(status=response.status_code, body=response.content,
                headers={k:v for k,v in response.headers.items() if k.lower() not in {'content-length','content-encoding'}})
        page.route('https://workspace.test/**', respond)
        try:
            page.goto('https://workspace.test/hfl-corpus/graph?'+urlencode({'workspace':work['id'], 'source':'git', 'board':board['id']}))
            page.wait_for_selector('#kg-workspace:not([inert])')
            expect(page.locator('[data-board-id="'+board['id']+'"]')).to_have_count(1)
            expect(page.locator('[data-board-id="'+other['id']+'"]')).to_have_count(0)
            expect(page.locator('#kg-list')).to_contain_text('Context member')
            expect(page.locator('#kg-list')).to_contain_text('Outside workspace filters')
            page.locator('#kg-entities').click()
            frame = page.locator('.activity-entities-drawer iframe')
            assert 'context=' not in frame.get_attribute('src')
            assert 'graph_filters=' not in frame.get_attribute('src')
            page.locator('.activity-entities-drawer').evaluate('(el)=>el.close()')
            page.locator('[data-workspace-menu] > summary').click()
            expect(page.locator('[data-view-picker]')).to_be_visible()
            first_label = page.locator('[data-view-choices] label').first
            assert float(first_label.evaluate('(el)=>getComputedStyle(el).fontSize').removesuffix('px')) > 0
            trigger = page.locator('[data-workspace-menu] > summary')
            page.mouse.move(0, 0)
            assert trigger.evaluate('(el)=>getComputedStyle(el).backgroundColor') == 'rgb(37, 99, 235)'
            assert trigger.bounding_box()['height'] == 36
            if width == 1440:
                search = page.locator('#kg-search').bounding_box()
                animation = page.locator('#kg-open-animation').bounding_box()
                workspace = trigger.bounding_box()
                refresh = page.locator('#kg-reload').bounding_box()
                assert animation['x'] >= search['x']+search['width']
                assert animation['x'] < search['x']+search['width']+30
                assert workspace['x'] > refresh['x']+refresh['width']
                entities = page.locator('#kg-entities').bounding_box()
                filters = page.locator('#kg-open-filters').bounding_box()
                assert entities['x'] >= workspace['x']+workspace['width']
                # Board mode intentionally hides the activity Filters button.
                if filters:
                    assert filters['x'] >= entities['x']+entities['width']

            panel = page.locator('.workspace-menu-panel').bounding_box()
            assert panel['x'] >= 0 and panel['x']+panel['width'] <= width+1
            assert panel['width'] >= min(280, width-24)
            page.screenshot(path=str(tmp_path / ('graph-workspace-'+str(width)+'.png')))
            if width == 1440:
                # A failed workspace read leaves the current canvas and caption intact.
                page.route('**/timeline/ideas/maps/*/graph?**', lambda route: route.fulfill(status=503, json={'detail':'Offline'}))
                page.locator('[data-view-picker] > summary').click()
                page.locator('[data-view-all]').click()
                expect(page.locator('[data-adaptive-status]')).to_contain_text('previous view and edits are retained')
                expect(page.locator('[data-active-view-name]')).to_have_text('Work')
                expect(page.locator('#kg-list')).to_contain_text('Context member')
                page.unroute('**/timeline/ideas/maps/*/graph?**')
                page.locator('[data-adaptive-status]').get_by_role('button', name='Retry').click()
                expect(page.locator('[data-active-view-name]')).to_have_text('All activity')
            page.locator('[data-workspace-menu]').evaluate('(el)=>el.open=false')
            page.get_by_role('button', name='Explore Activity Graph', exact=True).click()
            expect(page.locator('#kg-open-filters')).to_be_visible()
            if width == 1440:
                entities = page.locator('#kg-entities').bounding_box()
                filters = page.locator('#kg-open-filters').bounding_box()
                assert filters['x'] >= entities['x']+entities['width']
                assert abs(filters['y']-page.locator('#kg-search').bounding_box()['y']) <= 2
            page.screenshot(path=str(tmp_path / ('graph-toolbar-'+str(width)+'.png')))
            page.locator('[data-workspace-menu] > summary').click()
            panel = page.locator('.workspace-menu-panel').bounding_box()
            assert panel['x'] >= 0 and panel['x']+panel['width'] <= width+1
            assert not errors, errors
        finally:
            browser.close()
