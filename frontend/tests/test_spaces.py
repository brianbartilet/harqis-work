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
    expect(page.get_by_role('button',name='Discard changes',exact=True)).to_be_disabled()
    page.get_by_label('Name',exact=True).fill('Learning')
    page.locator('[data-applied-filters] > summary').click()
    page.locator('[data-edit-filter=q]').fill('#work')
    expect(page.locator('[data-space-tags-selected] button')).to_have_text('#work')
    page.locator('[data-space-tag-search]').fill('personal')
    page.locator('[data-space-tags] button').click()
    expect(page.locator('[data-edit-filter=q]')).to_have_value('#work #personal')
    page.locator('[data-space-tags-selected] [data-space-tag=personal]').click()
    expect(page.locator('[data-edit-filter=q]')).to_have_value('#work')
    page.locator('[data-space-tag-search]').fill('')
    page.locator('[data-edit-filter=rolling]').select_option('7')
    expect(page.locator('[data-edit-filter=date_from]')).to_be_disabled()
    page.get_by_role('button',name='Add time block').click()
    page.get_by_role('button',name='Weekends',exact=True).click()
    expect(page.get_by_role('checkbox',name='Saturday',exact=True)).to_be_checked()
    expect(page.get_by_role('checkbox',name='Monday',exact=True)).not_to_be_checked()
    page.get_by_role('button',name='All week',exact=True).click()
    expect(page.locator('.workspace-day-options input:checked')).to_have_count(7)
    page.get_by_role('button',name='Weekdays',exact=True).click()
    page.get_by_role('checkbox',name='Friday',exact=True).focus()
    page.keyboard.press('Space')
    expect(page.get_by_role('button',name='Weekdays',exact=True)).to_have_attribute('aria-pressed','false')
    page.get_by_role('button',name='Save Space',exact=True).click()
    expect(page.locator('#space-status')).to_contain_text('Space saved')
    saved=client.get('/hfl-corpus/workspace-views').json()['views'][0]
    assert saved['state']['q']=='#work' and saved['state']['rolling']==7
    assert len(saved['schedule'])==1
    assert saved['schedule'][0]['days']==[0,1,2,3]
    page.reload()
    page.locator('.space-card').click()
    expect(page.get_by_role('checkbox',name='Thursday',exact=True)).to_be_checked()
    expect(page.get_by_role('checkbox',name='Friday',exact=True)).not_to_be_checked()
    expect(page.locator('[data-edit-filter=q]')).to_have_value('#work')
    expect(page.locator('[data-space-tags-selected] button')).to_have_text('#work')
    page.locator('[data-applied-filters] > summary').click()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.get_by_label('Name',exact=True).fill('Unsaved name')
    page.locator('[data-edit-filter=q]').fill('Unsaved search #personal')
    page.get_by_role('button',name='All week',exact=True).click()
    page.get_by_role('button',name='Discard changes',exact=True).click()
    expect(page.get_by_label('Name',exact=True)).to_have_value('Learning')
    expect(page.locator('[data-edit-filter=q]')).to_have_value('#work')
    expect(page.locator('.workspace-day-options input:checked')).to_have_count(4)
    assert client.get('/hfl-corpus/workspace-views').json()['views'][0]==saved
    from pathlib import Path
    Path('logs').mkdir(exist_ok=True)
    page.evaluate('window.scrollTo(0,0)')
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


def test_combined_handoff_requires_target_and_conflicts_keep_edits(editor_page, workspace_corpus):
    from playwright.sync_api import expect
    from modules.hfl_corpus import workspace_views
    page,client=editor_page
    first=workspace_views.save(workspace_views.WorkspaceWrite(name='Work',state={'q':'#work'}))
    second=workspace_views.save(workspace_views.WorkspaceWrite(name='Personal',state={'q':'#personal'}))
    page.goto('https://editing.test/hfl-corpus?views='+first['id']+','+second['id']+'&q=planning')
    page.locator('[data-workspace-menu]').evaluate('(e)=>e.open=true')
    page.locator('[data-manage-spaces]').click()
    expect(page.locator('#space-handoff-text')).to_contain_text('additional filters only')
    expect(page.locator('#space-destination')).to_have_value('')
    page.locator('#space-apply-draft').click()
    expect(page.locator('#space-form')).to_be_hidden()
    page.locator('#space-destination').select_option(first['id'])
    page.locator('#space-apply-draft').click()
    expect(page.locator('[data-edit-filter=q]')).to_have_value('planning')
    workspace_views.save(workspace_views.WorkspaceWrite(name='Changed elsewhere',state=first['state'],revision=first['revision']),first['id'])
    page.get_by_role('button',name='Save Space',exact=True).click()
    expect(page.locator('#space-error')).to_contain_text('Your edits are still here')
    expect(page.locator('[data-edit-filter=q]')).to_have_value('planning')
    saved=client.get('/hfl-corpus/workspace-views').json()['views']
    assert next(v for v in saved if v['id']==first['id'])['name']=='Changed elsewhere'
    assert next(v for v in saved if v['id']==second['id'])['state']['q']=='#personal'


def test_spaces_auth_and_navigation(authenticated_client):
    client=authenticated_client
    html=client.get('/spaces').text
    assert html.index('>Spaces</a>') < html.index('>Facets</a>') < html.index('>Files</a>')
    assert 'spaces.js?v=' in html or 'spaces.js?' in html
    client.cookies.clear()
    assert client.get('/spaces',follow_redirects=False).status_code in (302,303,307)


def test_existing_space_tags_survive_unavailable_catalog(editor_page, workspace_corpus, monkeypatch):
    from playwright.sync_api import expect
    from modules.hfl_corpus import workspace_views
    from modules.spaces import router as routes
    from modules.hfl_corpus.remote import RemoteCorpusError
    page, client = editor_page
    state = {'q': 'Project planning #Wo #unlisted', 'source': 'git,notes', 'rolling': 30}
    schedule = [{'days': [0, 1], 'start': '09:00', 'end': '17:00'}]
    saved = workspace_views.save(workspace_views.WorkspaceWrite(name='Existing', state=state, schedule=schedule))
    monkeypatch.setattr(routes, '_uses_remote_corpus', lambda: True)
    def unavailable(*args, **kwargs):
        raise RemoteCorpusError('Unavailable')
    monkeypatch.setattr(routes.RemoteCorpusClient, 'from_settings', unavailable)
    page.goto('https://editing.test/spaces?edit=' + saved['id'])
    page.locator('[data-applied-filters] > summary').click()
    expect(page.locator('[data-space-tags-selected] button')).to_have_text(['#wo', '#unlisted'])
    page.locator('[data-space-tag-search]').fill('absent')
    expect(page.locator('[data-space-tags-selected] button')).to_have_count(2)
    page.get_by_role('button', name='Save Space', exact=True).click()
    expect(page.locator('#space-status')).to_contain_text('Space saved')
    actual = client.get('/hfl-corpus/workspace-views').json()['views'][0]
    assert actual['state'] == saved['state']
    assert actual['schedule'] == schedule
    page.locator('[data-space-tag=wo]').click()
    expect(page.locator('[data-edit-filter=q]')).to_have_value('Project planning #unlisted')
