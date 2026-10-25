from pathlib import Path

import pytest


@pytest.mark.parametrize('width', [1280, 390])
def test_board_search_keeps_queries_focus_and_selection(width, tmp_path):
    from playwright.sync_api import sync_playwright, expect

    root = Path(__file__).resolve().parents[1]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge')
        page = browser.new_page(viewport={'width': width, 'height': 850})
        template = (root / 'templates/modules/hfl_corpus/partials/followups_board.html').read_text(encoding='utf-8')
        # Use the real toolbar controls without the surrounding Jinja branches.
        toolbar = template.split('<div class="followups-toolbar">', 1)[1].split('{% if actions_page %}', 1)[0]
        page.route('http://localhost/preview', lambda route: route.fulfill(content_type='text/html', body=f'''
          <meta charset="utf-8"><main data-actions-page class="actions-page"><section id="followups-board" class="followups-board">
          <div class="followups-toolbar">{toolbar}<p data-board-error hidden></p></div>
          <div data-board-lanes class="followups-lanes"></div></section></main>'''))
        page.goto('http://localhost/preview')
        for name in ['app.min.css', 'hfl-timeline.css', 'hfl-intent-reuse.css', 'activity-header-sizing.css']:
            page.add_style_tag(path=str(root / 'static/css' / name))
        page.evaluate('''() => {
          window.testActions=[
            {id:'a',title:'Health module',status:'open',body:'Monitor services',version:1},
            {id:'b',title:'Magic feed',status:'active',description:'Card news',version:1,
              checklists:[{title:'Sources',items:[{text:'Find conjuring videos'}]}]},
            {id:'c',title:'Other',status:'open',version:1}];
          window.testIdeas=[
            {id:'i',title:'Voice research',status:'suggested',origin:'manual',body:'Local speech'},
            {id:'j',title:'Health idea',status:'suggested',origin:'manual',
              checklists:[{title:'Checks',items:[{text:'Uptime alerts'}]}]}];
          window.fetch=async()=>({ok:true,json:async()=>({items:testActions,total:testActions.length})});
          window.hflActions={load(){},openEditor(){},card(item){
            const card=document.createElement('article');card.className='agenda-card';
            card.dataset.followupId=item.id;card.textContent=item.title;return card;
          }};
          window.HflWorkspacePicker=()=>({});window.HflCopyIdButton=()=>document.createElement('span');
          window.HflObjectDescription=item=>item.body||item.description||'';
          window.HflChecklistMarkdown=(el,text)=>{el.textContent=text;};
          window.HflIdeas={api:async()=>({items:testIdeas})};
        }''')
        for name in ['vendor/sortablejs-1.15.2.min.js', 'js/hfl-bulk-actions.js', 'js/hfl-followups.js']:
            page.add_script_tag(path=str(root / 'static' / name))
        cards = page.locator('[data-followup-id]')
        search = page.get_by_role('searchbox', name='Search actions')
        expect(cards).to_have_count(3)
        page.locator('[data-bulk-kind="action"] [data-bulk-toggle]').click()
        page.locator('[data-followup-id="a"] [data-bulk-check]').check()
        search.fill('  CONJURING  ')
        expect(cards).to_have_count(1)
        expect(cards).to_have_attribute('data-followup-id', 'b')
        expect(page.locator('[data-board-status]')).to_have_text('1 of 3 actions')
        expect(page.locator('[data-bulk-kind="action"] [data-bulk-count]')).to_have_text('1 selected')
        search.fill('monitor')
        expect(cards).to_have_attribute('data-followup-id', 'a')
        expect(cards.locator('[data-bulk-check]')).to_be_checked()
        search.fill('unmatched')
        expect(cards).to_have_count(0)
        expect(page.get_by_text('No matching actions', exact=True)).to_have_count(6)
        search.fill('health')
        page.locator('.ideas-drawer-toggle').click()
        ideas = page.locator('[data-idea-id]')
        expect(ideas).to_have_count(2)
        idea_search = page.get_by_role('searchbox', name='Search ideas')
        idea_search.press_sequentially('UPTIME')
        expect(idea_search).to_be_focused()
        expect(idea_search).to_have_value('UPTIME')
        expect(ideas).to_have_count(1)
        expect(ideas).to_have_attribute('data-idea-id', 'j')
        expect(cards).to_have_attribute('data-followup-id', 'a')
        # A refresh that changes data must preserve the search input and focus.
        page.evaluate("testIdeas.push({id:'k',title:'Uptime dashboard',status:'suggested',origin:'manual'}); window.dispatchEvent(new Event('hfl:ideas-updated'))")
        expect(ideas).to_have_count(2)
        expect(idea_search).to_be_focused()
        idea_search.fill('no match')
        expect(page.get_by_text('No matching ideas', exact=True)).to_be_visible()
        idea_search.fill('speech')
        expect(ideas).to_have_attribute('data-idea-id', 'i')
        idea_search.fill('')
        expect(ideas).to_have_count(3)
        drawer = page.locator('.ideas-drawer')
        assert idea_search.bounding_box()['width'] <= drawer.bounding_box()['width']
        page.screenshot(path=str(tmp_path / f'ideas-search-{width}.png'))
        page.get_by_role('button', name='Close ideas drawer').click()
        search.fill('')
        expect(cards).to_have_count(3)
        expect(page.locator('[data-followup-id="a"] [data-bulk-check]')).to_be_checked()
        search_box = search.bounding_box()
        assert search_box['x'] >= 0 and search_box['x'] + search_box['width'] <= width
        page.screenshot(path=str(tmp_path / f'actions-search-{width}.png'))
        browser.close()
