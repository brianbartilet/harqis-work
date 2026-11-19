"""Persisted list sorting and scoped moves, without touching live actions."""
from pathlib import Path

import pytest


def test_sort_preferences_auth_persistence_and_conflicts(authenticated_client):
    from fastapi.testclient import TestClient
    from main import app
    from modules.hfl_corpus import kanban_preferences as prefs
    from modules.hfl_shares.security import make_csrf_token

    client = authenticated_client
    url = '/hfl-corpus/kanban/preferences'
    headers = {'x-csrf-token': make_csrf_token('frontend-test-user')}
    with TestClient(app) as anonymous:
        assert anonymous.get(url).status_code == 401
    first = client.get(url).json()['sorting']
    assert all(v == {'sort': 'updated_desc', 'revision': 0} for v in first.values())
    payload = {'status': 'open', 'sort': 'name', 'revision': 0}
    assert client.put(url, json=payload).status_code == 403
    assert client.put(url, json=payload, headers=headers).status_code == 200
    assert client.put(url, json=payload, headers=headers).status_code == 409
    assert client.put(url, json={**payload, 'sort': 'invalid'}, headers=headers).status_code == 422
    assert client.put(url, json={**payload, 'revision': True}, headers=headers).status_code == 422
    # A fresh connection retains the preference; another owner has independent defaults.
    assert prefs.listing('frontend-test-user')['sorting']['open'] == {'sort': 'name', 'revision': 1}
    assert prefs.listing('another-owner')['sorting']['open']['sort'] == 'updated_desc'
    # An edit to a different list does not conflict or overwrite the first list.
    assert client.put(url, json={'status': 'done', 'sort': 'created_asc', 'revision': 0}, headers=headers).status_code == 200
    assert client.get(url).json()['sorting']['open']['sort'] == 'name'


@pytest.mark.parametrize('width', [1440, 390])
def test_list_sort_and_filtered_move(width, tmp_path):
    from playwright.sync_api import sync_playwright, expect

    root = Path(__file__).resolve().parents[1]
    with sync_playwright() as engine:
        browser = engine.chromium.launch(channel='msedge')
        page = browser.new_page(viewport={'width': width, 'height': 850}, has_touch=width < 600)
        page.route('http://kanban.test/', lambda route: route.fulfill(content_type='text/html', body='''
          <meta charset="utf-8"><main data-actions-page class="actions-page">
          <section id="followups-board" class="agenda-dialog followups-board">
          <div class="followups-toolbar"><details data-board-create-menu><summary>Create</summary>
          <button data-board-create-action>Action</button><button data-board-create-idea>Idea</button></details>
          <input type="search" data-board-search aria-label="Search actions"><button data-board-refresh>Refresh</button>
          <div data-board-bulk></div><span data-board-status></span><p data-board-context hidden></p><p data-board-error hidden></p></div>
          <div data-board-lanes class="followups-lanes"></div></section></main>'''))
        page.goto('http://kanban.test/')
        for name in ['app.min.css', 'hfl-timeline.css']:
            page.add_style_tag(path=str(root / 'static/css' / name))
        page.evaluate('''() => {
          window.testRows=[
            {id:'a',title:'Zebra match',status:'open',version:1,created_at:'2026-01-03',updated_at:'2026-02-01'},
            {id:'b',title:'Alpha match',status:'open',version:1,created_at:'2026-01-01',updated_at:'2026-02-03'},
            {id:'c',title:'Hidden task',status:'open',version:1,created_at:'2026-01-02',updated_at:'2026-02-02'}];
          window.savedSorting={};window.patches=[];window.failNextSort=false;
          window.fetch=async(url,options={})=>{
            if(url.includes('/kanban/preferences')){
              if(options.method==='PUT'){
                if(failNextSort){failNextSort=false;return {ok:false,json:async()=>({detail:'Sorting changed elsewhere. Refresh and choose again.'})};}
                const p=JSON.parse(options.body);savedSorting[p.status]={sort:p.sort,revision:p.revision+1};
              }
              return {ok:true,json:async()=>({sorting:structuredClone(savedSorting)})};
            }
            if(options.method==='PATCH'){
              const id=url.split('/').pop(),p=JSON.parse(options.body);patches.push({id,...p});
              if(id==='a')return {ok:false,json:async()=>({detail:'Action changed elsewhere.'})};
              const row=testRows.find(r=>r.id===id);Object.assign(row,p,{version:row.version+1});
              return {ok:true,json:async()=>({item:row})};
            }
            return {ok:true,json:async()=>({items:structuredClone(testRows),total:testRows.length})};
          };
          window.HflEntitySemantics={action:{labels:{open:'In Review',active:'Ready',in_progress:'In Progress',incomplete:'Incomplete',done:'Completed',dismissed:'Dismissed'}},idea:{labels:{suggested:'Suggested'}}};
          window.hflActions={load(){},openEditor(){},card(item){const c=document.createElement('article');c.className='agenda-card';c.dataset.followupId=item.id;c.textContent=item.title;return c;}};
          window.HflWorkspacePicker=()=>({});
          window.HflIdeas={api:async()=>({items:[]}),dialog(title){
            const d=document.createElement('dialog');d.className='agenda-dialog';
            d.innerHTML='<form><header><h2></h2></header><div class="body"></div><p class="error"></p><footer><button type="button">Cancel</button></footer></form>';
            d.querySelector('h2').textContent=title;document.body.append(d);d.showModal();
            d.querySelector('button').onclick=()=>d.close();d.addEventListener('close',()=>d.remove());
            return {node:d,form:d.querySelector('form'),body:d.querySelector('.body'),footer:d.querySelector('footer'),error:d.querySelector('.error')};
          }};
        }''')
        for name in ['vendor/sortablejs-1.15.7.min.js', 'js/hfl-bulk-actions.js', 'js/hfl-followups.js']:
            page.add_script_tag(path=str(root / 'static' / name))
        lane = page.locator('[data-status="open"]')
        cards = lane.locator('[data-followup-id]')
        expect(cards).to_have_count(3)
        ids = lambda: cards.evaluate_all('(cards)=>cards.map(c=>c.dataset.followupId)')
        assert ids() == ['b', 'c', 'a']
        menu = lane.get_by_role('button', name='In Review list actions')
        menu.click()
        expect(page.get_by_text('Updated · newest', exact=True)).to_be_visible()
        expect(page.get_by_text('3 matching actions', exact=True)).to_be_visible()
        page.get_by_role('button', name='Sort by', exact=True).press('ArrowRight')
        expect(page.get_by_role('button', name='Updated date (newest)', exact=True)).to_be_focused()
        page.locator('.kanban-list-menu').press('ArrowLeft')
        expect(page.get_by_role('button', name='Sort by', exact=True)).to_be_focused()
        page.locator('.kanban-list-menu').press('Escape')
        choices = [('Updated date (oldest)', ['a','c','b']), ('Created date (newest)', ['a','c','b']),
                   ('Created date (oldest)', ['b','c','a']), ('Name (alphabetical)', ['b','c','a'])]
        for choice, order in choices:
            menu.click()
            page.get_by_role('button', name='Sort by', exact=True).click()
            panel = page.locator('.kanban-list-menu')
            box = panel.bounding_box()
            assert box['x'] >= 0 and box['x'] + box['width'] <= width
            assert box['y'] >= 0 and box['y'] + box['height'] <= 850
            assert box['width'] <= 260
            if width == 1440:
                assert box['height'] < 220
            page.get_by_role('button', name=choice, exact=True).click()
            expect(panel).to_have_count(0)
            assert ids() == order
        # Refresh uses the saved preference; a rejected save does not change it.
        page.get_by_role('button', name='Refresh', exact=True).click()
        menu.click();page.get_by_role('button', name='Sort by', exact=True).click()
        expect(page.get_by_role('button', name='Name (alphabetical)', exact=True)).to_have_attribute('aria-pressed','true')
        page.screenshot(path=str(tmp_path / f'kanban-sort-{width}.png'))
        page.evaluate('failNextSort=true')
        page.get_by_role('button', name='Updated date (oldest)', exact=True).click()
        expect(page.locator('[data-board-error]')).to_contain_text('Sorting changed elsewhere')
        assert page.evaluate('savedSorting.open.sort') == 'name'
        # Keyboard dismissal restores focus; an empty filtered list cannot bulk move.
        menu.click();page.locator('.kanban-list-menu').press('Escape');expect(menu).to_be_focused()
        search = page.get_by_role('searchbox', name='Search actions')
        menu.click();search.click()
        expect(page.locator('.kanban-list-menu')).to_have_count(0)
        expect(search).to_be_focused()
        search.fill('no results');menu.click()
        expect(page.get_by_role('button', name='Move all actions to status', exact=True)).to_be_disabled()
        page.locator('.kanban-list-menu').press('Escape');search.fill('match')
        menu.click();page.get_by_role('button', name='Move all actions to status', exact=True).click()
        expect(page.get_by_role('button', name='In Review (current)', exact=True)).to_be_disabled()
        page.screenshot(path=str(tmp_path / f'kanban-move-{width}.png'))
        page.get_by_role('button', name='Ready', exact=True).click()
        expect(page.get_by_text('2 actions selected.', exact=True)).to_be_visible()
        assert page.evaluate('patches.length') == 0
        page.get_by_role('button', name='Move', exact=True).click()
        expect(page.get_by_text('1 updated · 1 failed.', exact=True)).to_be_visible()
        assert {p['id'] for p in page.evaluate('patches')} == {'a','b'}
        assert all(p['status'] == 'active' for p in page.evaluate('patches'))
        assert page.evaluate('testRows.find(r=>r.id==="c").status') == 'open'
        expect(page.get_by_text('Zebra match: Action changed elsewhere.', exact=True)).to_be_visible()
        page.get_by_role('button', name='Close', exact=True).click()
        expect(page.locator('[data-followup-id="a"] [data-bulk-check]')).to_be_checked()
        expect(menu).to_be_focused()
        if width == 1440:
            search.fill('')
            grip = page.locator('[data-followup-id="c"] .action-drag-handle')
            target = page.locator('[data-status="active"]')
            start, end = grip.bounding_box(), target.bounding_box()
            page.mouse.move(start['x'] + start['width']/2, start['y'] + start['height']/2)
            page.mouse.down()
            page.mouse.move(start['x'] + start['width']/2 + 10, start['y'] + start['height']/2, steps=3)
            page.mouse.move(end['x'] + end['width']/2, end['y'] + 150, steps=20)
            page.mouse.up()
            expect(page.locator('[data-status="active"] [data-followup-id="c"]')).to_have_count(1)
            assert page.evaluate('patches.at(-1).status') == 'active'
        browser.close()
