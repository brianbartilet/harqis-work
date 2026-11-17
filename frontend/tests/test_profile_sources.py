"""Source configuration, on-demand cache, update adoption and network boundaries."""
import json
import socket
import zipfile
import io

import pytest
from frontend.tests.test_fleet_specialists import fleet, bridge, catalog_data, selection
from frontend.tests.test_agent_fleet import post


def local_source(client,tmp_path,monkeypatch,name='Team profiles'):
    monkeypatch.setenv('HARQIS_PROFILE_SOURCE_ROOTS',str(tmp_path))
    (tmp_path/'review.md').write_text('---\nname: Team Reviewer\ndescription: Team review guidance\n---\n# Original guidance\n',encoding='utf-8')
    response=post(client,'/profile-sources',dict(name=name,type='local',location=str(tmp_path),ref='',paths=['*.md'],enabled=True))
    assert response.status_code==200,response.text
    source=response.json()['item']
    response=post(client,'/profile-sources/'+source['id']+'/refresh',{'version':source['version']})
    assert response.status_code==200,response.text
    return response.json()['item']


def test_browse_is_metadata_only_and_cached_body_survives_offline(fleet,authenticated_client,catalog_data):
    client=authenticated_client
    rows=client.get('/agents/api/specialists').json()['items']
    assert len(rows)==283 and catalog_data[1]==[]
    first=client.get('/agents/api/specialists/'+rows[0]['id'])
    assert first.status_code==200 and len(catalog_data[1])==1
    catalog_data[0][rows[0]['download_url']]=ValueError('Offline')
    assert client.get('/agents/api/specialists/'+rows[0]['id']).json()==first.json()
    assert len(catalog_data[1])==1
    with fleet.store().connect() as db:
        assert db.execute('SELECT count(*) FROM fleet_profile_cache').fetchone()[0]==1
    catalog_data[0][rows[1]['download_url']]=ValueError('Offline')
    assert client.get('/agents/api/specialists/'+rows[1]['id']).status_code==422


def test_refresh_diff_explicit_adoption_and_removed_source(fleet,authenticated_client,tmp_path,monkeypatch):
    client=authenticated_client
    source=local_source(client,tmp_path,monkeypatch)
    rows=client.get('/agents/api/specialists').json()['items']
    row=next(r for r in rows if r['source']==source['id'])
    item=post(client,'/items',{'name':'Team agent','instructions':'Keep my guidance.','specialist_profile':{k:row[k] for k in ('id','revision','hash')}}).json()['item']
    (tmp_path/'review.md').write_text('---\nname: Team Reviewer\ndescription: Updated\n---\n# New guidance\n',encoding='utf-8')
    refreshed=post(client,'/profile-sources/'+source['id']+'/refresh',{'version':source['version']}).json()['item']
    assert refreshed['changes']=={'added':0,'removed':0,'changed':1}
    assert 'Original guidance' in fleet.execution(item['id'])['fleet_agent']['instructions']
    preview=post(client,'/specialist-update-preview',{'agent_id':item['id']}).json()
    assert '-# Original guidance' in preview['diff'] and '+# New guidance' in preview['diff']
    current=preview['profile']
    updated=post(client,'/items/'+item['id'],{'version':1,'specialist_profile':{k:current[k] for k in ('id','revision','hash')}}).json()['item']
    assert updated['instructions']=='Keep my guidance.'
    assert 'New guidance' in fleet.execution(item['id'])['fleet_agent']['instructions']
    assert post(client,'/profile-sources/'+source['id']+'/remove',{'version':source['version']}).status_code==422
    assert post(client,'/profile-sources/'+source['id']+'/remove',{'version':refreshed['version']}).status_code==200
    assert 'New guidance' in fleet.execution(item['id'])['fleet_agent']['instructions']
    assert post(client,'/items/'+item['id'],{'version':2,'name':'Still usable','specialist_profile':updated['specialist_profile']}).status_code==200


def test_legacy_snapshot_survives_disabled_source(fleet,authenticated_client):
    client=authenticated_client
    row=selection(client)
    item=post(client,'/items',{'name':'Legacy','specialist_profile':row}).json()['item']
    legacy={**item['specialist_profile'],'id':item['specialist_profile']['id'].split(':',1)[1]}
    fleet.store().save({**item,'specialist_profile':legacy},identity=item['id'],version=1)
    source=client.get('/agents/api/profile-sources').json()['items'][0]
    payload={k:source[k] for k in ('name','type','location','ref','paths','version')}
    assert post(client,'/profile-sources/agency-agents',{**payload,'enabled':False}).status_code==200
    assert client.get('/agents/api/specialists').json()['items']==[]
    assert post(client,'/items/'+item['id'],{'version':2,'specialist_profile':legacy,'name':'Legacy still works'}).status_code==200
    assert 'Code Reviewer' in fleet.execution(item['id'])['fleet_agent']['instructions']


def test_source_failure_retains_index_and_stale_update_rejected(fleet,authenticated_client,monkeypatch):
    from modules.agents import profile_sources as sources
    client=authenticated_client
    source=sources.get('agency-agents')
    def fail(_): raise ValueError('Offline')
    monkeypatch.setattr(sources,'discover',fail)
    assert post(client,'/profile-sources/agency-agents/refresh',{'version':1}).status_code==422
    assert len(client.get('/agents/api/specialists').json()['items'])==283
    assert sources.get('agency-agents')['error']=='Offline'
    payload={k:source[k] for k in ('name','type','location','ref','paths','version','enabled')}
    assert post(client,'/profile-sources/agency-agents',payload).status_code==200
    assert post(client,'/profile-sources/agency-agents',payload).status_code==422


def test_github_discovery_pins_revision_without_caching_bodies(fleet,authenticated_client,catalog_data):
    from modules.agents import profile_sources as sources
    client=authenticated_client
    source=post(client,'/profile-sources',dict(name='Example',type='github',location='team/profiles',ref='main',paths=['agents/*.md'],enabled=True)).json()['item']
    revision='a'*40
    catalog_data[0]['https://api.github.com/repos/team/profiles/commits/main']=json.dumps({'sha':revision}).encode()
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('profiles-'+revision+'/','')
        z.writestr('profiles-'+revision+'/agents/reviewer.md','---\nname: Reviewer\ndescription: Review carefully\n---\nInstructions.')
        z.writestr('profiles-'+revision+'/README.md','# Not a profile')
    catalog_data[0]['https://codeload.github.com/team/profiles/zip/'+revision]=archive.getvalue()
    response=post(client,'/profile-sources/'+source['id']+'/refresh',{'version':1})
    assert response.status_code==200,response.text
    row=next(row for row in sources.catalog() if row['source']==source['id'])
    assert row['revision']==revision and '/'+revision+'/' in row['download_url']
    with fleet.store().connect() as db:
        assert db.execute('SELECT count(*) FROM fleet_profile_cache').fetchone()[0]==0
    catalog_data[0][row['download_url']]=b'---\nname: Reviewer\ndescription: Review carefully\n---\nInstructions.'
    assert client.get('/agents/api/specialists/'+row['id']).status_code==200
    catalog_data[1].clear()
    assert post(client,'/profile-sources/'+source['id']+'/refresh',{'version':2}).status_code==200
    assert catalog_data[1]==['https://api.github.com/repos/team/profiles/commits/main']
    newer='b'*40
    catalog_data[0]['https://api.github.com/repos/team/profiles/commits/main']=json.dumps({'sha':newer}).encode()
    catalog_data[0][f'https://api.github.com/repos/team/profiles/compare/{revision}...{newer}']=json.dumps({'status':'ahead','total_commits':1,'files':[{'filename':'agents/reviewer.md','status':'modified'}]}).encode()
    catalog_data[0][f'https://raw.githubusercontent.com/team/profiles/{newer}/agents/reviewer.md']=b'---\nname: Reviewer\ndescription: Improved review\n---\nNew instructions.'
    catalog_data[1].clear()
    updated=post(client,'/profile-sources/'+source['id']+'/refresh',{'version':3})
    assert updated.status_code==200,updated.text
    assert updated.json()['item']['changes']['changed']==1
    assert not any('codeload' in url for url in catalog_data[1])


def test_manifest_source_and_duplicate_ids(fleet,authenticated_client,catalog_data,monkeypatch):
    from modules.agents import profile_sources as sources
    client=authenticated_client
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))])
    source=post(client,'/profile-sources',dict(name='Catalog',type='manifest',location='https://example.com/catalog.json',ref='',paths=['*.md'],enabled=True)).json()['item']
    content=b'# Standalone instructions'
    entry=dict(id='review',name='Reviewer',description='Review',url='https://example.com/review-v1.md',hash=sources.sha(content))
    catalog_data[0][source['location']]=json.dumps({'revision':'v1','profiles':[entry]}).encode()
    catalog_data[0][entry['url']]=content
    assert post(client,'/profile-sources/'+source['id']+'/refresh',{'version':1}).status_code==200
    assert client.get('/agents/api/specialists/'+source['id']+':review').json()['content']==content.decode()
    catalog_data[0][source['location']]=json.dumps({'revision':'v2','profiles':[entry,entry]}).encode()
    assert post(client,'/profile-sources/'+source['id']+'/refresh',{'version':2}).status_code==422
    assert sources.get(source['id'])['revision']=='v1'


def test_skill_package_is_preview_only_and_local_path_is_bounded(fleet,authenticated_client,tmp_path,monkeypatch):
    client=authenticated_client
    source=local_source(client,tmp_path,monkeypatch)
    (tmp_path/'SKILL.md').write_text('---\nname: Package\ndescription: Requires supporting files\n---\nRun scripts/helper.py',encoding='utf-8')
    assert post(client,'/profile-sources/'+source['id']+'/refresh',{'version':2}).status_code==200
    row=next(r for r in client.get('/agents/api/specialists').json()['items'] if r.get('kind')=='skill-package')
    assert client.get('/agents/api/specialists/'+row['id']).status_code==200
    assert post(client,'/items',{'name':'Incomplete package','specialist_profile':{k:row[k] for k in ('id','revision','hash')}}).status_code==422
    assert post(client,'/profile-sources',dict(name='Outside',type='local',location=str(tmp_path.parent),ref='',paths=['*.md'],enabled=True)).status_code==422


@pytest.mark.parametrize('url',['http://example.com/x','https://user:pass@example.com/x','https://example.com:8080/x','file:///etc/passwd'])
def test_invalid_source_urls(fleet,authenticated_client,url):
    assert post(authenticated_client,'/profile-sources',dict(name='Bad',type='manifest',location=url,ref='',paths=['*.md'],enabled=True)).status_code==422


def test_private_addresses_and_csrf_rejected(fleet,authenticated_client,monkeypatch):
    from modules.agents import profile_sources as sources
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))])
    with pytest.raises(ValueError,match='private'):
        sources.public_url('https://example.com/catalog')
    assert authenticated_client.post('/agents/api/profile-sources',json={}).status_code==403


def test_source_collision_and_concurrent_refresh(fleet,authenticated_client,tmp_path,monkeypatch):
    from modules.agents import profile_sources as sources
    client=authenticated_client
    a=local_source(client,tmp_path,monkeypatch,'A')
    b=local_source(client,tmp_path,monkeypatch,'B')
    rows=[r for r in sources.catalog() if r['source'] in {a['id'],b['id']}]
    assert len(rows)==2 and rows[0]['id']!=rows[1]['id']
    original=sources.discover
    def edit_during_discovery(source):
        result=original(source)
        sources.save({**{k:source[k] for k in sources.CONFIG},'name':'Concurrent edit','version':source['version']},source['id'])
        return result
    monkeypatch.setattr(sources,'discover',edit_during_discovery)
    assert post(client,'/profile-sources/'+a['id']+'/refresh',{'version':a['version']}).status_code==422
    assert sources.get(a['id'])['name']=='Concurrent edit'
