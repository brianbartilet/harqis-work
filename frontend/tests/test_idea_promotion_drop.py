from pathlib import Path

import pytest


@pytest.mark.parametrize('width', [1280, 390])
def test_idea_drag_uses_promotion_target_and_restores_card(width, tmp_path):
    from playwright.sync_api import sync_playwright, expect
    root = Path(__file__).resolve().parents[1] / 'static'
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge')
        page = browser.new_page(viewport={'width': width, 'height': 850})
        page.route('http://localhost/preview', lambda route: route.fulfill(content_type='text/html', body='''
          <main data-actions-page><section id="followups-board" class="followups-board">
          <div class="followups-toolbar"><div data-board-bulk></div><span data-board-status></span>
          <p data-board-context></p><p data-board-error hidden></p><button data-board-refresh>Refresh</button>
          <details data-board-create-menu><summary>Create</summary><button data-board-create-action>Action</button><button data-board-create-idea>Idea</button></details></div>
          <div data-board-lanes class="followups-lanes"></div></section></main>'''))
        page.goto('http://localhost/preview')
        for name in ['hfl-timeline.css', 'hfl-intent-reuse.css']:
            page.add_style_tag(path=str(root / 'css' / name))
        page.evaluate('''() => {
          window.promotions=[];
          window.fetch=async()=>({ok:true,json:async()=>({items:[],total:0})});
          window.hflActions={load(){},card(){return document.createElement('article')},openEditor(){}};
          window.HflWorkspacePicker=()=>({});window.HflCopyIdButton=()=>document.createElement('span');
          window.HflObjectDescription=()=>'';
          window.HflIdeas={api:async()=>({items:[{id:'idea-one',title:'Test idea',status:'suggested',origin:'manual'}]}),convert:id=>promotions.push(id)};
        }''')
        for path in ['vendor/sortablejs-1.15.7.min.js', 'js/hfl-bulk-actions.js', 'js/hfl-followups.js']:
            page.add_script_tag(path=str(root / path))
        page.locator('.ideas-drawer-toggle').click()
        card = page.locator('[data-idea-id="idea-one"]')
        expect(card).to_be_visible()
        zone = page.locator('.idea-promotion-dropzone')
        expect(zone).to_be_hidden()
        grip = card.locator('.action-drag-handle').bounding_box()
        page.mouse.move(grip['x']+10, grip['y']+10)
        page.mouse.down()
        page.mouse.move(grip['x']+20, grip['y']+20, steps=5)
        expect(zone).to_be_visible()
        target = zone.bounding_box()
        page.mouse.move(target['x']+target['width']/2, target['y']+target['height']/2, steps=20)
        expect(zone).to_have_class('idea-promotion-dropzone is-over')
        page.screenshot(path=str(tmp_path / 'promotion.png'))
        assert page.locator('[data-board-lanes] [data-idea-id]').count() == 0
        page.mouse.up()
        expect(zone).to_be_hidden()
        assert page.evaluate('promotions') == ['idea-one']
        expect(page.locator('.ideas-drawer [data-idea-id="idea-one"]')).to_be_visible()
        browser.close()


def test_action_projection_links_existing_promotions(tmp_path):
    from workflows.hfl.timeline_store import FollowUpStore
    from workflows.hfl.ideas_store import IdeasStore
    store = FollowUpStore(tmp_path / 'timeline.sqlite3')
    IdeasStore(store)
    from uuid import uuid4
    action, _ = store.create({'title': 'Promoted action', 'request_id': str(uuid4())}, actor='owner')
    assert store.get(action['id'])['origin_idea_ids'] == []
    with store.connect() as db:
        db.execute('INSERT INTO idea_links VALUES (?,?,?,?)', ('idea:original', 'action:'+action['id'], 'develops-into', '2026-10-13'))
    assert store.get(action['id'])['origin_idea_ids'] == ['original']
    assert store.list()[0]['origin_idea_ids'] == ['original']
    assert store.get(action['id'])['status'] == 'open'
