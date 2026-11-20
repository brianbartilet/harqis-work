"""Fleet inventory must survive a large activity corpus at the API boundary."""
import pytest


@pytest.mark.parametrize('limit', [100, 1000])
def test_inventory_survives_activity_budget(authenticated_client, monkeypatch, limit):
    from modules.agents import ecosystem
    inventory = [dict(id='agent:n8n', kind='agent'), dict(id='owner', kind='owner'),
                 dict(id='agent:gina', kind='agent'), dict(id='hud:one', kind='hud'), dict(id='n8n:app', kind='application'),
                 dict(id='n8n:trigger', kind='trigger'), dict(id='n8n:config', kind='configuration')]
    inventory += [dict(id=f'n8n:workflow:{i}', kind='workflow', source='n8n', state='archived' if i else 'inactive') for i in range(8)]
    inventory += [dict(id=f'skills:repo:skill-{i}', kind='skill', definition=True, agent_ids=['gina']) for i in range(47)]
    history = [dict(id=f'entry:{i:05}', kind='entry') for i in range(17000)]
    history += [dict(id=f'action:{i}', kind='action') for i in range(150)]
    nodes = history + inventory
    edges = [dict(source='agent:n8n', target=n['id']) for n in nodes if n['id'] != 'agent:n8n']
    skill_edges = [dict(source='agent:gina', target=n['id'], relation='configured') for n in inventory if n['kind'] == 'skill']
    edges += skill_edges
    monkeypatch.setattr(ecosystem, 'graph', lambda user: dict(nodes=nodes, edges=edges, coverage={}, warnings=[]))
    response = authenticated_client.get('/agents/api/graph', params={'node_limit': limit})
    assert response.status_code == 200
    result = response.json()
    ids = {n['id'] for n in result['nodes']}
    assert {n['id'] for n in inventory} <= ids
    assert all(edge in result['edges'] for edge in skill_edges)
    assert len(result['nodes']) == limit
    assert all(e['source'] in ids and e['target'] in ids for e in result['edges'])
    assert result['coverage']['graph']['total'] == len(nodes)
    assert result['coverage']['graph']['has_more']
