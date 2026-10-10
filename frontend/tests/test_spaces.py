"""Spaces management and shared dropdown handoffs use the real isolated APIs."""
import pytest
from test_action_editing import editor_page
from test_hfl_ideas import ideas
from test_corpus_workspaces import workspace_corpus

@pytest.mark.parametrize('width',[1440,390])
def test_manage_spaces(editor_page, workspace_corpus, width):
    from playwright.sync_api import expect
    page, client = editor_page
    page.set_viewport_size({'width':width,'height':1000})
    page.goto('https://editing.test/spaces')
    page.get_by_role('button',name='New Space',exact=True).click()
    page.get_by_label('Name',exact=True).fill('Learning')
    page.locator('[data-applied-filters] > summary').click()
    page.locator('[data-edit-filter=q]').fill('#work')
    page.locator('[data-edit-filter=rolling]').select_option('7')
    expect(page.locator('[data-edit-filter=date_from]')).to_be_disabled()
    page.get_by_role('button',name='Add time block').click()
    page.get_by_role('button',name='Save Space',exact=True).click()
    expect(page.locator('#space-status')).to_contain_text('Space saved')
    saved=client.get('/hfl-corpus/workspace-views').json()['views'][0]
    assert saved['state']['q']=='#work' and saved['state']['rolling']==7
    assert len(saved['schedule'])==1
    page.reload()
    page.locator('.space-card').click()
    expect(page.locator('[data-edit-filter=q]')).to_have_value('#work')
    page.locator('[data-applied-filters] > summary').click()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    from pathlib import Path
    Path('logs').mkdir(exist_ok=True)
    page.screenshot(path=f'logs/spaces-{width}.png',full_page=True)
    page.get_by_role('button',name='Remove Space',exact=True).click()
    page.locator('#space-delete-cancel').click()
    assert len(client.get('/hfl-corpus/workspace-views').json()['views'])==1
    page.get_by_role('button',name='Remove Space',exact=True).click()
    page.locator('#space-delete-confirm').click()
    expect(page.locator('#space-status')).to_contain_text('Space removed')
    assert not client.get('/hfl-corpus/workspace-views').json()['views']

@pytest.mark.parametrize('path',['/hfl-corpus','/hfl-corpus/graph','/hfl-corpus/actions'])
def test_dropdown_handoff(editor_page, workspace_corpus, path):
    from playwright.sync_api import expect
    page,client=editor_page
    page.goto('https://editing.test'+path+'?reset=1&q=planning')
    menu=page.locator('[data-workspace-menu]')
    menu.evaluate('(e)=>e.open=true')
    assert menu.locator('[data-workspace-action]').count()==0
    for name in ['Visualize','Generate share recipe','Sharing preview']:
        expect(menu.get_by_role('button',name=name,exact=True)).to_be_visible()
    assert menu.locator('[data-workspace-help-open]').evaluate('(e)=>getComputedStyle(e).borderTopWidth')=='0px'
    menu.get_by_role('link',name='Manage Spaces').click()
    expect(page.locator('#space-handoff')).to_be_visible()
    assert not client.get('/hfl-corpus/workspace-views').json()['views']
    page.locator('#space-destination').select_option('new')
    page.locator('#space-apply-draft').click()
    expect(page.locator('[data-edit-filter=q]')).to_have_value('planning')
    page.get_by_label('Name',exact=True).fill('From activity')
    page.get_by_role('button',name='Save Space',exact=True).click()
    expect(page.locator('#space-status')).to_contain_text('Space saved')
    assert client.get('/hfl-corpus/workspace-views').json()['views'][0]['state']['q']=='planning'
