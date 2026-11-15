"""Keyboard workflows through isolated APIs and real browser events."""
from test_action_editing import editor_page
from test_hfl_ideas import ideas
from test_hfl_timeline import payload
from test_corpus_workspaces import workspace_corpus
import re
import pytest
from playwright.sync_api import expect


@pytest.mark.parametrize('surface', ['', '/graph', '/actions'])
def test_keyboard_help_toggles_with_k(editor_page, workspace_corpus, surface):
    page, _ = editor_page
    page.goto('https://editing.test/hfl-corpus' + surface)
    trigger = page.locator('.activity-hotkey-trigger')
    trigger.focus()
    helper = page.locator('#activity-hotkey-help')
    for _ in range(2):
        page.keyboard.press('k')
        expect(helper).to_be_visible()
        page.keyboard.press('k')
        expect(helper).not_to_be_visible()
        expect(trigger).to_be_focused()
    trigger.click()
    expect(helper).to_be_visible()
    page.keyboard.press('k')
    expect(helper).not_to_be_visible()


@pytest.mark.parametrize('width', [390, 1440])
def test_kanban_shortcut_context_and_confirmation(editor_page, ideas, width):
    page, client = editor_page
    page.set_viewport_size({'width':width,'height':1000})
    first = client.post('/hfl-corpus/timeline/items', json=payload(title='Keyboard action')).json()['item']
    page.goto('https://editing.test/hfl-corpus/actions?all=1')
    card = page.locator(f'[data-board-lanes] [data-followup-id="{first["id"]}"]')
    expect(card).to_be_visible()
    page.evaluate("document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'k',repeat:true,bubbles:true}))")
    expect(page.locator('#activity-hotkey-help')).not_to_be_visible()
    page.keyboard.press('k')
    expect(page.locator('#activity-hotkey-help')).to_be_visible()
    assert page.locator('#activity-hotkey-help').bounding_box()['width'] <= width
    page.keyboard.press('a')
    expect(page.locator('#followup-editor')).not_to_be_visible()
    page.keyboard.press('Escape')
    card.focus()
    page.keyboard.press('c')
    dismiss = page.get_by_role('dialog', name='Dismiss this action?')
    expect(dismiss).to_be_visible()
    dismiss.get_by_role('button', name='Cancel', exact=True).click()
    page.keyboard.press('o')
    confirm = page.get_by_role('dialog', name='Done this action?')
    expect(confirm).to_be_visible()
    confirm.get_by_role('button', name='Cancel', exact=True).click()
    expect(card.locator('.action-status')).to_have_text('In Review')
    page.keyboard.press('o')
    confirm.get_by_role('button', name='Done this action', exact=True).click()
    expect(card.locator('.action-status')).to_have_text('Done')
    page.mouse.move(0, 0)
    page.locator('[data-board-refresh]').focus()
    page.keyboard.press('i')
    expect(page.locator('.ideas-drawer')).to_be_visible()
    page.keyboard.press('m')
    expect(page.locator('[data-bulk-kind=idea] [data-bulk-toggle]')).to_have_attribute('aria-pressed','true')
    page.keyboard.press('Escape')
    page.keyboard.press('a')
    expect(page.locator('#followup-editor')).to_be_visible()
    page.keyboard.press('k')
    expect(page.locator('#activity-hotkey-help')).not_to_be_visible()


def test_graph_shortcuts_and_board_space(editor_page):
    page, client = editor_page
    page.goto('https://editing.test/hfl-corpus/graph')
    page.wait_for_selector('#kg-workspace:not([inert])')
    page.keyboard.press('f')
    expect(page.locator('#kg-filter-drawer')).to_be_visible()
    page.keyboard.press('Escape')
    page.keyboard.press('Backslash')
    expect(page.locator('.kg-shell')).to_have_class(re.compile('kg-fullscreen'))
    page.keyboard.press('Backslash')
    expect(page.locator('.kg-shell')).not_to_have_class(re.compile('kg-fullscreen'))
    page.evaluate("async () => { const maps=HflIdeas.maps; await HflIdeas.api('/maps','POST',{request_id:crypto.randomUUID(),name:'Keyboard board',members:[],drafts:[{id:'draft:keyboard',title:'Keyboard thought',body:''}]}); await maps.reload(); await maps.selectBoard(maps.loaded.find(item=>item.name==='Keyboard board')); }")
    page.keyboard.press('Space')
    expect(page.locator('.idea-dialog[open]')).to_contain_text('Attach')
    page.keyboard.press('Escape')
    page.locator('#kg-list').get_by_role('button',name=re.compile('Keyboard thought')).click()
    page.locator('.activity-hotkey-trigger').focus()
    page.keyboard.press('ArrowUp')
    page.wait_for_function("HflIdeas.maps.current.node_sizes['draft:keyboard']===4")
    page.keyboard.press('ArrowDown')
    page.wait_for_function("HflIdeas.maps.current.node_sizes['draft:keyboard']===3")
    page.keyboard.press('e')
    expect(page.locator('.idea-dialog[open]')).to_contain_text('Edit thought')
    page.keyboard.press('Escape')
    page.locator('.activity-hotkey-trigger').focus()
    page.keyboard.press('x')
    expect(page.locator('#kg-orb-actions-menu')).not_to_be_visible()
    page.evaluate("""() => {
      window.boardShortcutCalls=[];
      HflIdeas.maps.saveNow=()=>boardShortcutCalls.push('save');
      HflIdeas.maps.saveLayout=()=>boardShortcutCalls.push('layout');
    }""")
    page.keyboard.press('Control+s')
    page.keyboard.press('Control+l')
    assert page.evaluate('boardShortcutCalls') == ['save','layout']
    page.keyboard.press('Control+e')
    expect(page.get_by_role('dialog').filter(has=page.get_by_role('heading',name='Settings',exact=True))).to_be_visible()
    page.keyboard.press('Control+s')
    assert page.evaluate('boardShortcutCalls') == ['save','layout']
    page.keyboard.press('Escape')
    page.locator('.activity-hotkey-trigger').focus()
    page.keyboard.press('Control+d')
    expect(page.get_by_role('dialog').filter(has=page.get_by_role('heading',name='Delete board',exact=True))).to_be_visible()
    page.keyboard.press('Escape')


def test_corpus_shortcuts_and_space_order(editor_page, workspace_corpus):
    from modules.hfl_shares.security import make_csrf_token
    page, client = editor_page
    for name in ('First Space','Second Space'):
        response=client.post('/hfl-corpus/workspace-views',json={'name':name,'state':{}},headers={'X-CSRF-Token':make_csrf_token('frontend-test-user')})
        assert response.status_code == 200
    page.goto('https://editing.test/hfl-corpus')
    page.locator('.activity-hotkey-trigger').focus()
    page.keyboard.press('d')
    expect(page.get_by_role('dialog').filter(has=page.get_by_role('heading',name='New idea',exact=True))).to_be_visible()
    page.keyboard.press('Escape')
    page.keyboard.press('k')
    expect(page.locator('#activity-hotkey-help')).to_be_visible()
    page.keyboard.press('Escape')
    tags=page.locator('[data-tag-cloud]')
    was_open=tags.evaluate('(el)=>el.open')
    page.keyboard.press('t')
    assert tags.evaluate('(el)=>el.open') != was_open
    toggle = page.locator('[data-activity-toggle]')
    if toggle.get_attribute('aria-expanded') == 'true':
        toggle.click()
    expect(toggle).to_have_attribute('aria-expanded', 'false')
    page.locator('.activity-hotkey-trigger').focus()
    page.keyboard.press('Space')
    expect(toggle).to_have_attribute('aria-expanded', 'true')
    expect(page.locator('[data-activity-day][data-today="true"]')).to_be_focused()
    expect(page.locator('#activity-cell-tooltip')).to_be_visible()
    page.evaluate("""() => {
      const body = document.querySelector('[data-activity-body]');
      window.tooltipVisibleAtCollapse = null;
      new MutationObserver(() => {
        if (body.hidden) window.tooltipVisibleAtCollapse = !document.querySelector('#activity-cell-tooltip').hidden;
      }).observe(body, {attributes:true, attributeFilter:['hidden']});
    }""")
    page.keyboard.press('Space')
    expect(toggle).to_have_attribute('aria-expanded', 'false')
    assert page.evaluate('tooltipVisibleAtCollapse') is False
    expect(page.locator('[data-activity-day][data-today="true"]')).not_to_have_attribute('aria-describedby', 'activity-cell-tooltip')
    page.keyboard.press('Space')
    expect(toggle).to_have_attribute('aria-expanded', 'true')
    expect(page.locator('[data-activity-day][data-today="true"]')).to_be_focused()
    expect(page.locator('#activity-cell-tooltip')).to_be_visible()
    page.keyboard.press('c')
    expect(page.locator('[data-memory-dialog]')).to_be_visible()
    page.locator('[data-memory-dialog-close]').first.click()
    expect(page.locator('[data-memory-dialog]')).not_to_be_visible()
    # A typing target must not switch Space or open help.
    for key, selector in [('q', '[data-quick-tags-menu]'), ('e', '[data-exclude-tags-menu]'), ('t', '[data-tag-cloud]'), ('r', '[data-advanced-filters]')]:
        section = page.locator(selector)
        section.evaluate('(el) => el.open = false')
        page.locator('.activity-hotkey-trigger').focus()
        page.keyboard.press(key)
        expect(section).to_have_attribute('open', '')
        if key == 'r':
            expect(section.locator('[data-expression-toggle]')).to_be_checked()
        if key in ('q', 'e'):
            expect(section.locator('summary')).to_be_focused()
        page.keyboard.press(key)
        expect(section).not_to_have_attribute('open', '')
    page.locator('[data-quick-tags-menu]').evaluate('(el) => el.open = false')
    page.locator('.activity-hotkey-trigger').focus()
    page.keyboard.press('w')
    expect(page.locator('[data-exclude-tags-menu]')).not_to_have_attribute('open', '')
    search=page.locator('#corpus-search-form input[name=q]')
    search.focus()
    page.keyboard.press('k')
    expect(page.locator('#activity-hotkey-help')).not_to_be_visible()
    page.locator('.activity-hotkey-trigger').focus()
    expected=page.locator('[data-view-choices] label').nth(0).text_content().strip()
    page.keyboard.press('Alt+1')
    expect(page.locator('[data-active-view-name]')).to_have_text(expected)
    expect(page.locator('[data-dynamic-badge]')).to_have_text('Dynamic OFF')
    page.keyboard.press('Alt+Backquote')
    expect(page.locator('[data-active-view-name]')).to_have_text('All activity')
    page.locator('.activity-hotkey-trigger').focus()
    page.keyboard.press('d')
    expect(page.get_by_role('dialog').filter(has=page.get_by_role('heading',name='New idea',exact=True))).to_be_visible()


@pytest.mark.parametrize('path', ['/hfl-corpus/actions', '/hfl-corpus', '/hfl-corpus/graph'])
def test_dialog_backdrop_dismissal(editor_page, path):
    page, _ = editor_page
    page.goto('https://editing.test'+path)
    trigger=page.get_by_role('button',name='Keyboard shortcuts',exact=True)
    trigger.click()
    dialog=page.locator('#activity-hotkey-help')
    dialog.locator('h2').click()
    expect(dialog).to_be_visible()
    # A drag beginning inside the dialog is not a backdrop click.
    box=dialog.bounding_box()
    page.mouse.move(box['x']+30,box['y']+30)
    page.mouse.down()
    page.mouse.move(2,2)
    page.mouse.up()
    expect(dialog).to_be_visible()
    page.mouse.click(2,2)
    expect(dialog).not_to_be_visible()
    expect(trigger).to_be_focused()
    # Dynamic dialogs inherit dismissal and can veto it while busy.
    page.evaluate("""() => {
      const d=document.createElement('dialog');d.id='dynamic-test-dialog';
      d.textContent='Saving';d.style.cssText='margin:auto;width:200px;height:100px';
      d.addEventListener('cancel',e=>{if(d.dataset.saving==='true')e.preventDefault();});
      d.dataset.saving='true';document.body.append(d);d.showModal();
    }""")
    page.mouse.click(2,2)
    expect(page.locator('#dynamic-test-dialog')).to_be_visible()
    page.locator('#dynamic-test-dialog').evaluate("d=>d.dataset.saving='false'")
    page.mouse.click(2,2)
    expect(page.locator('#dynamic-test-dialog')).not_to_be_visible()


@pytest.mark.parametrize('retry_fails', [False, True])
def test_share_preview_automatically_limits_dates(editor_page, retry_fails):
    import json
    import re
    from datetime import date, timedelta
    page, _ = editor_page
    states=[]
    def preview(route):
        body=route.request.post_data
        states.append(json.loads(re.search(r'name="state"\r\n\r\n(.*?)\r\n',body).group(1)))
        failed=len(states)==1 or retry_fails
        route.fulfill(status=422 if failed else 200,content_type='text/html',body=(
            '<div data-preview-error data-preview-size-limit>Selected activity exceeds the snapshot size limit.</div>'
            if failed else '<section data-preview-ready>Preview ready</section>'))
    page.route('**/sharing/from-corpus?mode=preview',preview)
    page.goto('https://editing.test/hfl-corpus/actions?all=1')
    page.locator('[data-corpus-share-preview]').evaluate('(el)=>el.click()')
    warning=page.locator('[data-preview-warning]')
    expect(warning).to_contain_text('last 15 days')
    assert len(states)==2
    assert states[1]['date_from']==(date.today()-timedelta(days=14)).isoformat()
    assert states[1]['date_to']==date.today().isoformat()
    assert states[1]['rolling']==0
    expect(page.get_by_role('button',name='Use last 15 days')).to_have_count(0)
    if retry_fails:
        expect(page.locator('[data-preview-error]')).to_be_visible()
    else:
        expect(page.locator('[data-preview-ready]')).to_be_visible()
        transfers=[]
        def recipe(route):
            from urllib.parse import parse_qs
            transfers.append(json.loads(parse_qs(route.request.post_data)['state'][0]))
            route.fulfill(content_type='text/html',body='<h1>Recipe draft</h1>')
        page.route('**/sharing/from-corpus',recipe)
        page.locator('[data-corpus-share-dialog] [data-corpus-share-generate]').click()
        expect(page.get_by_role('heading',name='Recipe draft')).to_be_visible()
        assert transfers==[states[1]]
