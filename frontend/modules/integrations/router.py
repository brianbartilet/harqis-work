"""Authenticated and CSRF-protected connector API."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from modules.hfl_corpus.agent_bridge import owner_auth
from modules.integrations import store, service, agents
from modules.integrations.providers import Provider, credentials, repository, segment, branch
import uuid

router = APIRouter(prefix='/integrations')
api = APIRouter(prefix='/api', dependencies=[Depends(owner_auth)])


def provider_name(provider):
    if provider not in service.PROVIDERS:
        raise HTTPException(404, 'Connector not found.')
    return provider


@api.post('/grokbot/login/start')
def grokbot_login_start(user=Depends(owner_auth)):
    from modules.integrations.grokbot import start_login
    return start_login(user)


@api.post('/grokbot/login/{identity}/poll')
def grokbot_login_poll(identity: str, user=Depends(owner_auth)):
    from modules.integrations.grokbot import poll_login
    return poll_login(user, identity)


@api.post('/grokbot/login/{identity}/cancel')
def grokbot_login_cancel(identity: str, user=Depends(owner_auth)):
    from modules.integrations.grokbot import cancel
    return cancel(user, identity)


@api.post('/grokbot/connect-key')
def grokbot_connect_key(raw: dict, user=Depends(owner_auth)):
    from modules.integrations.grokbot import connect_key
    return connect_key(user, raw.get('key'))


@api.post('/grokbot/sync')
def grokbot_sync(raw: dict, user=Depends(owner_auth)):
    from modules.integrations.grokbot import sync
    if type(raw.get('if_stale', False)) is not bool:
        raise HTTPException(422, 'Invalid refresh option.')
    return sync(user, raw.get('if_stale', False))


@api.post('/n8n/sync')
def sync_n8n(raw: dict, user=Depends(owner_auth)):
    from modules.integrations.n8n import sync
    query = raw.get('query', '')
    if not isinstance(query, str) or len(query) > 200:
        raise HTTPException(422, 'Keep the search under 200 characters.')
    return sync(user, query)


@api.get('/n8n/workflows')
def n8n_workflows(cursor: str = '', user=Depends(owner_auth)):
    _, client = service.connected(user, 'n8n')
    data = client.request('GET', '/workflows', params={'limit': 100, **({'cursor': cursor} if cursor else {})})
    return {'items': [{k: w.get(k) for k in ('id', 'name', 'active', 'updatedAt')} for w in data.get('data', [])],
            'cursor': data.get('nextCursor', '')}


@api.post('/n8n/agents/{identity}/refresh')
def refresh_n8n_agent(identity: str, user=Depends(owner_auth)):
    from modules.integrations.n8n import refresh_agent
    from workflows.hfl.agent_fleet_store import FleetConflict
    try:
        return refresh_agent(user, identity)
    except FleetConflict as exc:
        raise HTTPException(409, str(exc)) from None


@router.get('')
def page(request: Request):
    return RedirectResponse('/applications', status_code=307)


@api.get('/connectors')
def connectors(user=Depends(owner_auth)):
    items = [{**info, **store.get(user, key)} for key,info in service.PROVIDERS.items()]
    links = []
    for item in items:
        if item.get('enabled') and item.get('status') == 'Connected':
            links.extend({k:v for k,v in link.items() if k != 'creation'} for link in service.visible_links(user, item['provider']))
    return {'items':items, 'links':links}


@api.post('/connectors/{provider}/test')
def test_connection(provider: str, raw: dict, user=Depends(owner_auth)):
    provider_name(provider)
    if provider == 'grokbot':
        raise HTTPException(409, 'Use Grok Bot browser sign-in or Cursor API-key connection.')
    identity = Provider(provider, credentials(provider, raw)).test()
    return {'status': 'Test passed', **identity}


@api.post('/connectors/{provider}/save')
@api.post('/connectors/{provider}/connect')
def connect(provider: str, raw: dict, user=Depends(owner_auth)):
    provider_name(provider)
    if provider == 'grokbot':
        raise HTTPException(409, 'Use Grok Bot browser sign-in or Cursor API-key connection.')
    clean = credentials(provider, raw)
    # Revalidate before saving; a failed replacement must preserve the saved account.
    identity = Provider(provider, clean).test()
    previous = store.get(user, provider)
    metadata = {**identity, 'status':'Connected', 'enabled':False, 'connected_since':store.now(),
                'auth_method':('Fine-grained personal access token' if clean['token'].startswith('github_pat_') else 'Personal access token') if provider == 'github' else 'Email and API token',
                'expiry':'Unknown', 'site':clean.get('site', '')}
    if provider == 'n8n':
        metadata['auth_method'] = 'API key' + (' + MCP token' if clean.get('mcp_token') else '')
    if previous.get('account_id') == identity['account_id'] and previous.get('site','') == metadata['site']:
        metadata['connected_since'] = previous.get('connected_since', metadata['connected_since'])
    return store.save(user, provider, metadata, clean)


@api.post('/connectors/{provider}/toggle')
def toggle(provider: str, raw: dict, user=Depends(owner_auth)):
    provider_name(provider)
    if provider == 'grokbot':
        from modules.integrations.grokbot import toggle as toggle_grokbot
        return toggle_grokbot(user, raw.get('enabled'))
    if type(raw.get('enabled')) is not bool:
        raise HTTPException(422, 'Expected an enabled boolean.')
    data = store.get(user, provider, private=True)
    if raw['enabled']:
        if not data['credentials']:
            raise HTTPException(409, 'Connect and test before enabling.')
        try:
            Provider(provider, data['credentials']).test()
        except HTTPException as exc:
            store.save(user, provider, {**data, 'status':'Connection failure', 'enabled':False, 'error':exc.detail})
            raise
    data.update(enabled=raw['enabled'], status='Connected' if data['credentials'] else 'Not connected')
    data.pop('error', None)
    return store.save(user, provider, data)


@api.post('/connectors/{provider}/disconnect')
def disconnect(provider: str, user=Depends(owner_auth)):
    provider_name(provider)
    if provider == 'grokbot':
        from modules.integrations.grokbot import disconnect as disconnect_grokbot
        return disconnect_grokbot(user)
    return store.save(user, provider, {'status':'Not connected', 'enabled':False}, {})


@api.get('/github/repositories')
def repositories(page: int = 1, user=Depends(owner_auth)):
    _, client = service.connected(user, 'github')
    if not 1 <= page <= 1000:
        raise HTTPException(422, 'Invalid page.')
    rows = client.request('GET', '/user/repos', params={'per_page':50,'page':page,'sort':'updated'})
    return {'items':[{'name':r['full_name'], 'default_branch':r['default_branch'], 'permissions':r.get('permissions',{})} for r in rows], 'more':len(rows)==50}


@api.get('/github/branches')
def branches(repository_name: str, page: int = 1, user=Depends(owner_auth)):
    _, client = service.connected(user, 'github')
    repo = repository(repository_name)
    if not 1 <= page <= 1000:
        raise HTTPException(422, 'Invalid page.')
    rows = client.request('GET', '/repos/'+repo+'/branches', params={'per_page':50,'page':page})
    return {'items':[row['name'] for row in rows], 'more':len(rows)==50}


@api.get('/github/pulls')
def pull_requests(repository_name: str, branch_name: str, page: int = 1, user=Depends(owner_auth)):
    _, client = service.connected(user, 'github')
    repo, head = repository(repository_name), branch(branch_name)
    if not 1 <= page <= 1000:
        raise HTTPException(422, 'Invalid page.')
    rows = client.request('GET', '/repos/'+repo+'/pulls', params={
        'state':'all', 'head':repo.split('/')[0]+':'+head, 'per_page':50, 'page':page,
        'sort':'updated', 'direction':'desc',
    })
    return {'items':[{'number':p['number'], 'title':p['title'],
                      'state':'merged' if p.get('merged_at') else p['state'], 'draft':p.get('draft',False)}
                     for p in rows if p['head']['ref']==head and p['head'].get('repo',{}).get('full_name')==repo],
            'more':len(rows)==50}


@api.get('/github/resources')
def resources(repository_name: str, page: int = 1, user=Depends(owner_auth)):
    _, client = service.connected(user, 'github')
    repo = repository(repository_name)
    if not 1 <= page <= 1000:
        raise HTTPException(422, 'Invalid page.')
    branches = client.request('GET', '/repos/'+repo+'/branches', params={'per_page':50,'page':page})
    prs = client.request('GET', '/repos/'+repo+'/pulls', params={'state':'open','per_page':50,'page':page})
    return {'branches':[b['name'] for b in branches], 'pulls':[{'number':p['number'],'title':p['title'],'branch':p['head']['ref']} for p in prs], 'more':len(branches)==50 or len(prs)==50}


@api.get('/actions/{identity}')
def action_links(identity: str, user=Depends(owner_auth)):
    service.action(identity)
    result = {}
    for provider in service.PROVIDERS:
        data = store.get(user, provider)
        if data.get('enabled') and data.get('status') == 'Connected':
            result[provider] = [x for x in service.visible_links(user, provider) if x.get('action_id') == identity]
    return result


@api.post('/actions/{identity}/github/branch')
def github_branch(identity: str, raw: dict, user=Depends(owner_auth)):
    if raw.get('operation') not in {'link-branch','create-branch'}:
        raise HTTPException(422, 'Choose link or create branch.')
    return service.github_link(user, identity, raw)


@api.post('/actions/{identity}/github/pr')
def github_pr(identity: str, raw: dict, user=Depends(owner_auth)):
    return service.github_pr(user, identity, raw)


@api.get('/actions/{identity}/github')
def github_refresh(identity: str, user=Depends(owner_auth)):
    service.action(identity)
    return {'items':service.refresh_github(user, identity)}


@api.post('/actions/{identity}/github/clear')
def github_clear(identity: str, user=Depends(owner_auth)):
    service.action(identity)
    data, _ = service.connected(user, 'github')
    return {'removed':store.clear_action_links(user, 'github', identity, service.account_key(data))}


@api.get('/jira/projects')
def projects(start: int = 0, user=Depends(owner_auth)):
    _, client = service.connected(user, 'jira')
    if not 0 <= start <= 100000:
        raise HTTPException(422, 'Invalid start.')
    result = client.request('GET', '/rest/api/3/project/search', params={'startAt':start,'maxResults':50})
    return {'items':[{'key':p['key'],'name':p['name']} for p in result['values']], 'more':not result.get('isLast', True)}


@api.get('/boards')
def boards():
    from modules.hfl_corpus.ideas_api import canonical_snapshot
    return {'items':[{'id':b['id'],'name':b['name']} for b in canonical_snapshot()['maps'] if b.get('active',True)]}


@api.post('/jira/import')
def jira_import(raw: dict, user=Depends(owner_auth)):
    board_ids = raw.get('board_ids', [])
    if not isinstance(board_ids, list) or len(board_ids) > 1 or any(not isinstance(b,str) for b in board_ids):
        raise HTTPException(422, 'Choose at most one board.')
    if board_ids and not set(board_ids) <= {b['id'] for b in boards()['items']}:
        raise HTTPException(422, 'Board unavailable.')
    return service.jira_import(user, raw)


@api.get('/actions/{identity}/jira')
def jira_details(identity: str, user=Depends(owner_auth)):
    return service.jira_refresh(user, identity, persist=False)


@api.post('/actions/{identity}/jira/refresh')
def jira_refresh(identity: str, user=Depends(owner_auth)):
    return service.jira_refresh(user, identity)


@api.post('/actions/{identity}/jira/transition')
def jira_transition(identity: str, raw: dict, user=Depends(owner_auth)):
    return service.jira_transition(user, identity, raw)


@api.post('/github/ideas')
def github_ideas(raw: dict, user=Depends(owner_auth)):
    if type(raw.get('save', False)) is not bool:
        raise HTTPException(422, 'Choose preview or save.')
    _, client = service.connected(user, 'github')
    repo = repository(raw.get('repository'))
    kind, value = raw.get('kind'), raw.get('value')
    if kind == 'pr' and str(value).isdigit():
        remote = client.request('GET', '/repos/'+repo+'/pulls/'+str(value))
        title, url = remote['title'], 'https://github.com/'+repo+'/pull/'+str(value)
    elif kind == 'branch':
        from modules.integrations.providers import branch
        value = branch(value)
        client.request('GET', '/repos/'+repo+'/branches/'+segment(value))
        title, url = 'Explore '+repo+': '+value, 'https://github.com/'+repo+'/tree/'+segment(value)
    else:
        raise HTTPException(422, 'Choose a branch or pull request.')
    draft = {'request_id':str(uuid.uuid5(uuid.NAMESPACE_URL, user+':github-idea:'+url)), 'title':title[:200], 'body':'Review this GitHub work and identify next steps.\n\n'+url}
    if not raw.get('save'):
        return {'draft':draft}
    # Explicit save re-fetches provider evidence; arbitrary browser-supplied content is not trusted.
    from config import get_settings
    import os, httpx
    settings = get_settings()
    if settings.hfl_corpus_api_url and os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') != '1':
        try:
            response = httpx.post(settings.hfl_corpus_api_url.rstrip('/')+'/api/hfl/timeline/ideas/objects', json=draft,
                                  headers={'Authorization':'Bearer '+settings.hfl_corpus_api_token}, timeout=30)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError:
            raise HTTPException(502, 'Idea save could not be confirmed. Retry the same selection.') from None
    from modules.hfl_corpus.ideas_api import store as ideas, call
    return {'item':call(ideas().save_idea, draft, user)}


@api.post('/agents/prepare')
def prepare(raw: dict, user=Depends(owner_auth)):
    item = agents.prepare(user, raw)
    return {'item':item, 'agents':agents.AGENTS, 'workspace_url':agents.ADAPTERS[raw.get('agent','hermes')].workspace_url(item['id'])}


router.include_router(api)
