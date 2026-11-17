"""Action execution boundaries and profile inheritance, independent of provider calls."""
import copy
from uuid import uuid4

import pytest
from frontend.tests.test_agent_fleet import fleet
from frontend.tests.test_fleet_specialists import catalog_data, selection
from frontend.tests.test_hfl_agent_bridge import bridge, create_action, owner_headers

ROOT = '/hfl-corpus/agent-bridge'


def save(client, item, **changes):
    return client.post(ROOT+'/actions/'+item['id']+'/configuration', headers=owner_headers(),
                       json={'preset':'', 'overrides':{}, **changes})


def test_manual_assignment_blocks_runs_and_sessions(fleet, bridge, authenticated_client):
    module, _, actions = bridge
    item = create_action(actions)
    client = authenticated_client
    assert save(client, item, assignment_mode='manual').status_code == 200
    with pytest.raises(ValueError, match='Manual'):
        module.enqueue('actionable', item['id'], str(uuid4()), 'owner')
    assert client.post(ROOT+'/actions/'+item['id']+'/sessions', headers=owner_headers(),json={}).status_code == 400
    assert client.get(ROOT+'/sources/actionable/'+item['id']).json()['assignment']['executable'] is False
    assert client.get(ROOT+'/configuration/defaults').json()['card']['assignment_mode'] == 'manual'


def test_agent_profile_always_inherits_and_runs_are_frozen(fleet, bridge, authenticated_client, catalog_data):
    from modules.hfl_corpus.action_agents import effective
    client = authenticated_client
    profile = selection(client)
    response = client.post('/agents/api/items',headers=owner_headers(),json={'name':'Reviewer','specialist_profile':profile,'instructions':'Standing guidance'})
    agent = response.json()['item']
    item = create_action(bridge[2])
    response=save(client,item,assignment_mode='agent',agent_id=agent['id'],specialist_mode='inherit',additional_instructions='Only this Action')
    assert response.status_code == 200,response.text
    original=copy.deepcopy(effective(item['id']))
    assert original['fleet_agent']['specialist_profile']['hash']==profile['hash']
    assert 'Standing guidance' in original['fleet_agent']['instructions']
    assert 'Only this Action' in original['fleet_agent']['instructions']
    assert 'Only this Action' not in fleet.store().get(agent['id'])['instructions']
    assert save(client,item,specialist_mode='none').status_code == 200
    assert effective(item['id'])['fleet_agent']['specialist_profile']['hash']==profile['hash']
    assert original['fleet_agent']['specialist_profile']['hash']==profile['hash']
    assert save(client,item,specialist_mode='override',specialist_profile=profile).status_code == 200
    assert effective(item['id'])['fleet_agent']['specialist_profile']['hash']==profile['hash']
    assert save(client,item,specialist_mode='override',specialist_profile={'content':'Untrusted snapshot'}).status_code == 200
    assert effective(item['id'])['action_assignment']['specialist_mode']=='inherit'
    assert 'Untrusted snapshot' not in effective(item['id'])['action_assignment']['instructions']


def test_external_assignment_never_falls_back_to_hermes(fleet, bridge, authenticated_client):
    from modules.hfl_corpus.action_agents import effective
    client=authenticated_client
    agent=client.post('/agents/api/items',headers=owner_headers(),json={'name':'Codex reviewer','runtime':'codex'}).json()['item']
    item=create_action(bridge[2])
    result=save(client,item,assignment_mode='agent',agent_id=agent['id'])
    assert result.status_code==200,result.text
    assert result.json()['effective']['action_assignment']['executable'] is False
    with pytest.raises(ValueError,match='connector'):
        effective(item['id'])


def test_butler_assignment_records_coordination_context(fleet, bridge, authenticated_client):
    client=authenticated_client
    item=create_action(bridge[2])
    response=save(client,item,assignment_mode='butler')
    assert response.status_code==200,response.text
    run=bridge[0].enqueue('actionable',item['id'],str(uuid4()),'owner')
    settings=run['snapshot']['execution_settings']
    assert settings['fleet_agent']['id']=='butler'
    assert 'record meaningful progress' in settings['fleet_agent']['instructions']
    assert settings['action_assignment']['mode']=='butler'
    assert settings['fleet_agent']['hash']


def test_assignment_preview_is_read_only(fleet, bridge, authenticated_client):
    from modules.hfl_corpus.action_agents import store
    before=store().configs()
    result=authenticated_client.post(ROOT+'/configuration/preview',headers=owner_headers(),json={'assignment_mode':'butler','additional_instructions':'Report blockers'})
    assert result.status_code==200,result.text
    assert 'Report blockers' in result.json()['instructions']
    assert store().configs()==before
