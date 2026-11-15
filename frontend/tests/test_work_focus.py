"""Focus is canonical work, independent from graph presentation."""
import pytest
from test_agent_fleet import fleet
from test_hfl_agent_bridge import bridge
from workflows.hfl.agent_fleet_store import FleetConflict


def test_focus_unassigned_limits_and_conflicts(fleet, bridge, authenticated_client, monkeypatch):
    from modules.agents import work
    from modules.hfl_corpus import ideas_api, workspace_views
    rows=[{'id':'item-'+str(i),'title':'Action '+str(i),'status':'active','matrix':'Q2','created_at':'2026-11-15','workspace_ids':[]} for i in range(7)]
    monkeypatch.setattr(ideas_api,'canonical_snapshot',lambda **kw:{'actions':rows})
    monkeypatch.setattr(workspace_views,'listing',lambda:{'active':[],'views':[],'preferences':{'revision':1}})
    data=work.listing('owner',limit=2)
    assert data['coverage']['actions']['total']==7 and data['coverage']['actions']['has_more']
    assert data['items'][0]['owner']=='Unassigned'
    assert data['items'][0]['reasons']==['Important (Q2)']
    for i in range(5):work.pin('owner',{'id':rows[i]['id'],'pinned':True,'version':i})
    assert len(work.listing('owner')['commitments'])==5
    with pytest.raises(ValueError):work.pin('owner',{'id':rows[5]['id'],'pinned':True,'version':5})
    with pytest.raises(FleetConflict):work.pin('owner',{'id':rows[0]['id'],'pinned':False,'version':0})
    assert work.state('someone-else')['pins']==[]
    rows[0]['status']='done'
    data=work.listing('owner')
    assert len(data['commitments'])==4 and data['outside_focus']==[]
    assert rows[0]['id'] not in work.state('owner')['pins']
    assert data['state']['version']==6
    assert work.listing('owner')['state']['version']==6
    work.pin('owner',{'id':rows[5]['id'],'pinned':True,'version':6})
    rows[1]['status']='dismissed'
    removed=rows.pop(2)['id']
    rows[2]['workspace_ids']=['other']
    monkeypatch.setattr(workspace_views,'listing',lambda:{'active':['current'],'views':[],'preferences':{'revision':1}})
    data=work.listing('owner')
    assert rows[1]['id'] not in data['state']['pins'] and removed not in data['state']['pins']
    assert rows[2]['id'] in data['state']['pins']
    assert data['outside_focus']==[rows[2]['id']]
    assert len(data['state']['pins'])==3


def test_read_receipts_are_owner_scoped_and_revision_checked(fleet):
    from modules.agents import read_receipts
    saved=read_receipts.save('a',{'version':0,'keys':['result:v1'],'reviewed':True})
    assert saved['items']['result:v1']>0
    assert read_receipts.read('b')['items']=={}
    with pytest.raises(FleetConflict):read_receipts.save('a',{'version':0,'keys':['result:v1'],'reviewed':False})
    assert read_receipts.save('a',{'version':1,'keys':['result:v1'],'reviewed':False})['items']['result:v1']==0
    assert 'result:v2' not in read_receipts.read('a')['items']


@pytest.mark.parametrize('width',[390,1440])
def test_focus_drawer_keyboard_and_width(editor_page, width, tmp_path):
    from playwright.sync_api import expect
    page,client=editor_page
    page.set_viewport_size({'width':width,'height':900})
    item={'id':'action:a','record_id':'a','label':'Ship report','record':{'expected_outcome':'Approved report','matrix':'Q2','status':'active'},'agent_ids':['helper'],'owner':'Helper','reasons':['Important (Q2)'],'pinned':False,'url':'/hfl-corpus/actions?edit=a'}
    data={'agents':[{'id':'helper','name':'Helper','runtime':'codex','classification':'coding','color':'#67e8f9','thumbnail':'missing-test.png'}],'items':[item],'commitments':[],'attention':[],'attention_total':0,'suggestions':[item],'state':{'pins':[],'version':0},'outside_focus':[],'scope':{'label':'All activity'},'coverage':{'actions':{'total':1,'returned':1,'has_more':False},'executions':{'has_more':False}},'generated_at':'2026-11-15T00:00:00Z'}
    page.route('**/agents/api/work?*',lambda r:r.fulfill(json=data))
    page.goto('https://editing.test/hfl-corpus/actions')
    toggle=page.get_by_role('button',name='Show Focus',exact=True)
    expect(toggle).to_be_visible()
    for asset in ('focus-work.js','hfl-followups.js'):
        assert '?v=' in page.locator(f'script[src*="{asset}"]').get_attribute('src')
    assert '?v=' in page.locator('link[href*="hfl-intent-reuse.css"]').get_attribute('href')
    expect(toggle).to_have_attribute('data-items','new')
    page.locator('[data-board-refresh]').focus()
    page.keyboard.press('o');drawer=page.get_by_role('dialog',name='Focus',exact=True)
    expect(drawer).to_be_visible()
    expect(toggle).to_have_attribute('data-items','existing')
    expect(drawer.get_by_text('Choose up to five actions below to keep your next outcomes in view.')).to_be_visible()
    page.screenshot(path=str(tmp_path / f'focus-compact-{width}.png'))
    assert drawer.evaluate('(e) => e.scrollWidth <= e.clientWidth')
    expect(drawer.get_by_text('Helper · Important (Q2)').first).to_be_visible()
    expect(drawer.get_by_role('button',name='Commit',exact=True).first).to_be_visible()
    expect(drawer.locator('.focus-agent-avatars .agent-avatar').first).to_be_visible()
    expect(drawer.locator('.agent-avatar-initials').first).to_have_text('H')
    help_button=drawer.get_by_role('button',name='How Focus works')
    help_button.click()
    expect(drawer.get_by_text('Choose your next outcomes')).to_be_visible()
    bounds=drawer.locator('.focus-help-tip').bounding_box()
    assert bounds['x'] >= 0 and bounds['x']+bounds['width'] <= width
    page.screenshot(path=str(tmp_path / f'focus-help-{width}.png'))
    page.keyboard.press('Escape')
    expect(drawer).to_be_visible()
    expect(help_button).to_have_attribute('aria-expanded','false')
    help_button.click()
    drawer.get_by_role('button',name='Refresh Focus').click()
    expect(help_button).to_have_attribute('aria-expanded','false')
    assert abs(drawer.bounding_box()['width']-min(340,width-40))<2
    from test_action_editing import create_action
    action=create_action(client)
    page.route('**/hfl-corpus/timeline/items/a',lambda r:r.fulfill(json={'item':action}))
    page.evaluate("window.focusEditNavigationGuard=true")
    drawer.get_by_role('link',name='Ship report').first.click()
    editor=page.locator('#followup-editor')
    expect(editor).to_be_visible()
    assert drawer.evaluate('(e)=>e.open')
    assert page.evaluate("window.focusEditNavigationGuard") is True
    editor.get_by_role('button',name='Close follow-up editor').focus()
    page.keyboard.press('o')
    assert drawer.evaluate('(e)=>e.open')
    expect(editor).to_be_visible()
    page.screenshot(path=str(tmp_path / f'focus-edit-{width}.png'))
    editor.get_by_role('button',name='Close follow-up editor').click()
    expect(editor).not_to_be_visible()
    expect(drawer).to_be_visible()
    expect(drawer.get_by_role('link',name='Ship report').first).to_be_focused()
    drawer.get_by_role('link',name='Ship report').first.click()
    editor.locator('[name=title]').fill('Edited from Focus')
    editor.locator('[name=title]').press('Tab')
    expect(editor.locator('.editor-save-status')).to_have_text('Saved')
    assert client.get('/hfl-corpus/timeline/items/'+action['id']).json()['item']['title']=='Edited from Focus'
    editor.get_by_role('button',name='Close follow-up editor').click()
    expect(drawer.get_by_role('link',name='Ship report').first).to_be_focused()
    page.keyboard.press('o');expect(drawer).not_to_be_visible()
    expect(toggle).to_be_focused()
    data['items']=[];data['suggestions']=[];data['coverage']['actions']['total']=0;data['coverage']['actions']['returned']=0
    page.evaluate("window.dispatchEvent(new Event('hfl:actions-updated'))")
    expect(toggle).to_have_attribute('data-items','empty')
    page.keyboard.press('o')
    expect(drawer.get_by_text('No suggestions right now. Create an action in Kanban or explore another Space.')).to_be_visible()
    page.keyboard.press('Escape')
    ideas_toggle=page.get_by_role('button',name='Show ideas',exact=True)
    expect(ideas_toggle).to_have_attribute('data-items','empty')
    ideas_toggle.click()
    expect(page.get_by_text('No ideas yet. Use Create → Idea to capture something worth exploring.')).to_be_visible()
    page.keyboard.press('Escape')
    from datetime import datetime, timedelta, timezone
    now=datetime.now(timezone.utc)
    idea={'id':'test-idea','title':'Explore a compact view','status':'suggested','origin':'generated','created_at':(now-timedelta(days=1)).isoformat()}
    idea_rows=[idea]
    page.route('**/reuse/board-ideas?*',lambda r:r.fulfill(json={'items':idea_rows}))
    page.evaluate("window.dispatchEvent(new Event('hfl:ideas-updated'))")
    expect(ideas_toggle).to_have_attribute('data-items','new')
    ideas_toggle.click()
    expect(ideas_toggle).to_have_attribute('data-items','existing')
    expect(page.get_by_text('Explore a compact view',exact=True)).to_be_visible()
    dot=ideas_toggle.locator('.drawer-item-indicator')
    expect(dot).to_have_css('background-color','rgb(255, 255, 0)')
    expect(dot).to_have_css('position','absolute')
    page.screenshot(path=str(tmp_path / f'ideas-compact-{width}.png'))
    for change in ({'status':'dismissed'}, {'status':'adopted'}, {'created_at':(now-timedelta(days=8)).isoformat()}, {'created_at':'invalid'}, {'created_at':(now+timedelta(days=1)).isoformat()}):
        idea_rows[:]=[{**idea,**change}]
        page.evaluate("window.dispatchEvent(new Event('hfl:ideas-updated'))")
        expect(ideas_toggle).to_have_attribute('data-items','empty')
        expect(dot).not_to_be_visible()
    idea_rows[:]=[idea]
    page.evaluate("window.dispatchEvent(new Event('hfl:ideas-updated'))")
    expect(dot).to_be_visible()
    expect(dot).to_have_css('background-color','rgb(255, 255, 0)')

from test_action_editing import editor_page
from test_hfl_ideas import ideas


def test_graph_budget_and_conditional_response(fleet, authenticated_client, monkeypatch):
    from modules.agents import ecosystem
    from copy import deepcopy
    data={'nodes':[{'id':'entry:'+str(i),'kind':'entry'} for i in range(1200)]+[{'id':'agent:a','kind':'agent'}],
          'edges':[{'source':'agent:a','target':'entry:'+str(i)} for i in range(1200)],
          'coverage':{},'warnings':[],'generated_at':'2026-11-15'}
    monkeypatch.setattr(ecosystem,'graph',lambda user:deepcopy(data))
    first=authenticated_client.get('/agents/api/graph')
    assert first.status_code==200
    body=first.json();ids={n['id'] for n in body['nodes']}
    assert len(ids)==1000 and 'agent:a' in ids
    assert all(e['source'] in ids and e['target'] in ids for e in body['edges'])
    assert body['coverage']['graph']['total']==1201 and body['warnings']
    assert int(first.headers['x-projection-bytes'])==len(first.content)
    assert 'projection;dur=' in first.headers['server-timing']
    second=authenticated_client.get('/agents/api/graph',headers={'If-None-Match':first.headers['etag']})
    assert second.status_code==304 and not second.content
    assert authenticated_client.get('/agents/api/graph?node_limit=99999').status_code==422
