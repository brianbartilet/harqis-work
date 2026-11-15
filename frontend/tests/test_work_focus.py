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
    assert len(data['commitments'])==4 and rows[0]['id'] in data['outside_focus']
    work.pin('owner',{'id':rows[0]['id'],'pinned':False,'version':5})


def test_read_receipts_are_owner_scoped_and_revision_checked(fleet):
    from modules.agents import read_receipts
    saved=read_receipts.save('a',{'version':0,'keys':['result:v1'],'reviewed':True})
    assert saved['items']['result:v1']>0
    assert read_receipts.read('b')['items']=={}
    with pytest.raises(FleetConflict):read_receipts.save('a',{'version':0,'keys':['result:v1'],'reviewed':False})
    assert read_receipts.save('a',{'version':1,'keys':['result:v1'],'reviewed':False})['items']['result:v1']==0
    assert 'result:v2' not in read_receipts.read('a')['items']


@pytest.mark.parametrize('width',[390,1440])
def test_focus_drawer_keyboard_and_width(editor_page, width):
    from playwright.sync_api import expect
    page,client=editor_page
    page.set_viewport_size({'width':width,'height':900})
    item={'id':'action:a','record_id':'a','label':'Ship report','record':{'expected_outcome':'Approved report'},'owner':'Unassigned','reasons':['Important (Q2)'],'pinned':False,'url':'/hfl-corpus/actions?edit=a'}
    data={'items':[item],'commitments':[],'attention':[],'attention_total':0,'suggestions':[item],'state':{'pins':[],'version':0},'outside_focus':[],'scope':{'label':'All activity'},'coverage':{'actions':{'total':1,'returned':1,'has_more':False},'executions':{'has_more':False}},'generated_at':'2026-11-15T00:00:00Z'}
    page.route('**/agents/api/work?*',lambda r:r.fulfill(json=data))
    page.goto('https://editing.test/hfl-corpus/actions')
    toggle=page.get_by_role('button',name='Show Focus',exact=True)
    expect(toggle).to_be_visible()
    page.locator('[data-board-refresh]').focus()
    page.keyboard.press('o');drawer=page.get_by_role('dialog',name='Focus',exact=True)
    expect(drawer).to_be_visible()
    expect(drawer.get_by_text('Unassigned · Important (Q2)').first).to_be_visible()
    assert abs(drawer.bounding_box()['width']-min(340,width-40))<2
    page.keyboard.press('o');expect(drawer).not_to_be_visible()
    expect(toggle).to_be_focused()

from test_action_editing import editor_page
from test_hfl_ideas import ideas
