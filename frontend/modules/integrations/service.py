"""Connector operations and canonical action synchronization."""
import os
import uuid

import httpx
from fastapi import HTTPException
from config import get_settings
from modules.integrations import store
from modules.integrations.providers import Provider, repository, branch, segment, jira_status


PROVIDERS = {'github': {'name': 'GitHub', 'capabilities': ['Create and link branches', 'Create draft pull requests', 'Review linked pull requests', 'Save ideas from branches and PRs']},
             'jira': {'name': 'Jira Cloud', 'capabilities': ['Import assigned issues to Kanban', 'Update Jira status from action cards', 'Refresh issue status']}}


def connected(user, provider):
    data = store.get(user, provider, private=True)
    if not data.get('enabled') or data.get('status') != 'Connected':
        raise HTTPException(409, 'Enable a connected '+provider+' connector first.')
    return data, Provider(provider, data['credentials'])


def account_key(data):
    return data.get('site', '')+':'+data.get('account_id', '')


def visible_links(user, provider):
    data, _ = connected(user, provider)
    return [link for link in store.links(user, provider) if link.get('account_key') == account_key(data)]


def canonical(method, path, payload=None):
    """Use the same canonical host as Kanban, with isolated local-preview support."""
    settings = get_settings()
    if settings.hfl_corpus_api_url and os.getenv('HFL_TIMELINE_LOCAL_PREVIEW') != '1':
        try:
            with httpx.Client(timeout=30, follow_redirects=False) as client:
                response = client.request(method, settings.hfl_corpus_api_url.rstrip('/')+'/api/hfl'+path,
                                          headers={'Authorization':'Bearer '+settings.hfl_corpus_api_token}, json=payload)
            if not response.is_success:
                raise HTTPException(response.status_code, 'Canonical action changed or is unavailable. Refresh and retry.')
            return response.json()
        except httpx.HTTPError:
            raise HTTPException(502, 'Canonical action service unavailable. Refresh to reconcile before retrying.') from None
    from modules.hfl_corpus.timeline import store as actions
    from workflows.hfl.timeline_store import FollowUpConflict
    try:
        if path == '/actions' and method == 'POST':
            item, duplicate = actions().create({**payload, 'agent_enabled':False}, actor='connector')
            return {'item':item, 'duplicate':duplicate}
        identity = path.split('/')[-1]
        if method == 'GET':
            return {'item':actions().get(identity)}
        return {'item':actions().update(identity, payload, actor='connector')}
    except KeyError:
        raise HTTPException(404, 'Action unavailable.') from None
    except FollowUpConflict:
        raise HTTPException(409, 'Action changed. Refresh before retrying.') from None
    except ValueError:
        raise HTTPException(422, 'Invalid action fields.') from None


def action(identity):
    return canonical('GET', '/actions/'+segment(identity))['item']


def github_link(user, identity, raw):
    action(identity)
    data, client = connected(user, 'github')
    repo = repository(raw.get('repository'))
    name = branch(raw.get('branch'))
    base = branch(raw.get('base', 'main'))
    prefix = '/repos/'+repo
    # Validate access and reconcile an earlier successful request before creating.
    client.request('GET', prefix)
    ref = client.request('GET', prefix+'/git/ref/heads/'+segment(name), missing=True)
    if raw.get('operation') == 'create-branch' and ref is None:
        origin = client.request('GET', prefix+'/git/ref/heads/'+segment(base))
        ref = client.request('POST', prefix+'/git/refs', json={'ref':'refs/heads/'+name, 'sha':origin['object']['sha']})
    if ref is None:
        raise HTTPException(404, 'Branch not found. Create it or choose an existing branch.')
    resource = identity+':'+repo+':'+name
    link = {'action_id':identity, 'repository':repo, 'branch':name, 'base':base, 'url':'https://github.com/'+repo+'/tree/'+segment(name), 'account_key':account_key(data)}
    store.link(user, 'github', resource, link)
    return link


def github_pr(user, identity, raw):
    if not isinstance(raw.get('body', ''), str) or len(raw.get('body', '')) > 10000:
        raise HTTPException(422, 'Keep the PR description within 10,000 characters.')
    card = action(identity)
    data, client = connected(user, 'github')
    links = visible_links(user, 'github')
    link = next((x for x in links if x['resource'] == raw.get('resource') and x.get('action_id') == identity), None)
    if not link:
        raise HTTPException(404, 'Link a branch to this action first.')
    repo, head, base = link['repository'], link['branch'], link['base']
    prefix = '/repos/'+repo+'/pulls'
    number = raw.get('number')
    if number:
        if not str(number).isdigit():
            raise HTTPException(422, 'Enter a pull request number.')
        pr = client.request('GET', prefix+'/'+str(number))
        if pr['head']['ref'] != head or (pr['head'].get('repo') or {}).get('full_name') != link.get('head_repository', repo):
            raise HTTPException(422, 'Choose a PR whose head matches the linked repository and branch.')
    else:
        if link.get('pr_number'):
            return link
        head_repository = link.get('head_repository', repo)
        if head_repository != repo:
            raise HTTPException(422, 'Link an existing fork pull request by number.')
        found = client.request('GET', prefix, params={'state':'all','head':head_repository.split('/')[0]+':'+head,'base':base,'per_page':100})
        # Refuse to create a second PR after an ambiguous previous result, even if closed.
        pr = found[0] if found else client.request('POST', prefix, json={'title':card['title'], 'body':raw.get('body', '')[:10000], 'head':head, 'base':base, 'draft':True})
    link.update(pr_number=pr['number'], pr_url='https://github.com/'+repo+'/pull/'+str(pr['number']), pr_state='merged' if pr.get('merged_at') else pr['state'], draft=pr.get('draft', False))
    store.link(user, 'github', link['resource'], link)
    return link


def refresh_github(user, identity):
    _, client = connected(user, 'github')
    result = []
    for link in visible_links(user, 'github'):
        if link.get('action_id') != identity:
            continue
        if link.get('pr_number'):
            pr = client.request('GET', '/repos/'+link['repository']+'/pulls/'+str(link['pr_number']))
            link.update(pr_state='merged' if pr.get('merged') else pr['state'], draft=pr.get('draft', False))
            store.link(user, 'github', link['resource'], link)
        result.append(link)
    return result


def jira_import(user, raw):
    data, client = connected(user, 'jira')
    project = raw.get('project', '')
    if not isinstance(project, str) or not project or not project.replace('_','').isalnum() or len(project) > 100:
        raise HTTPException(422, 'Select a Jira project.')
    search = {'jql':'assignee = currentUser() AND project = "'+project+'" ORDER BY key', 'maxResults':50,
              'fields':['summary','status','assignee','project']}
    if raw.get('cursor'):
        search['nextPageToken'] = str(raw['cursor'])[:4000]
    issues = client.request('POST', '/rest/api/3/search/jql', json=search)
    results = []
    for issue in issues.get('issues', []):
        resource = account_key(data)+':'+issue['id']
        existing = next((x for x in store.links(user, 'jira') if x['resource'] == resource), None)
        if existing and existing.get('action_id'):
            card = action(existing['action_id'])
        else:
            # Persist immutable creation payload BEFORE dispatch, so timeout retries reuse it.
            creation = (existing or {}).get('creation') or {'request_id':str(uuid.uuid5(uuid.NAMESPACE_URL, user+':jira:'+resource)),
                         'title':(issue['key']+' · '+issue['fields']['summary'])[:200], 'body':'Jira issue: '+data['site']+'/browse/'+issue['key'],
                         'board_ids':raw.get('board_ids', [])}
            existing = {'account_key':account_key(data), 'issue_key':issue['key'], 'creation':creation}
            store.link(user, 'jira', resource, existing)
            card = canonical('POST', '/actions', creation)['item']
        existing.update(action_id=card['id'], url=data['site']+'/browse/'+issue['key'], jira_status=issue['fields']['status']['name'])
        store.link(user, 'jira', resource, existing)
        changes = {'status':jira_status(issue), 'title':(issue['key']+' · '+issue['fields']['summary'])[:200]}
        if any(card.get(k) != v for k,v in changes.items()):
            card = canonical('PATCH', '/actions/'+card['id'], {'version':card['version'], **changes})['item']
        results.append(card)
    return {'items':results, 'cursor':issues.get('nextPageToken', '')}


def jira_link(user, identity):
    return next((x for x in visible_links(user, 'jira') if x.get('action_id') == identity), None)


def jira_transition(user, identity, raw):
    data, client = connected(user, 'jira')
    link = jira_link(user, identity)
    if not link:
        raise HTTPException(404, 'This action has no Jira issue for your connection.')
    if type(raw.get('version')) is not int:
        raise HTTPException(422, 'Refresh the action version before changing Jira.')
    card = action(identity)
    if card['version'] != raw.get('version'):
        raise HTTPException(409, 'Action changed. Refresh before changing Jira.')
    issue = client.issue(link['issue_key'])
    if str(issue['fields']['status']['id']) != str(raw.get('expected_status')):
        raise HTTPException(409, 'Jira status changed. Refresh before choosing a transition.')
    selected = next((t for t in client.transitions(link['issue_key']) if t['id'] == str(raw.get('transition'))), None)
    if not selected:
        raise HTTPException(409, 'That transition is no longer available. Refresh.')
    if any(field.get('required') and not field.get('hasDefaultValue') for field in selected.get('fields', {}).values()):
        raise HTTPException(422, 'This transition requires additional fields. Complete it in Jira, then refresh here.')
    client.request('POST', '/rest/api/3/issue/'+segment(link['issue_key'])+'/transitions', json={'transition':{'id':selected['id']}})
    return jira_refresh(user, identity)


def jira_refresh(user, identity, *, persist=True):
    _, client = connected(user, 'jira')
    link = jira_link(user, identity)
    if not link:
        raise HTTPException(404, 'Jira link unavailable.')
    issue = client.issue(link['issue_key'])
    card = action(identity)
    if persist and card['status'] != jira_status(issue):
        card = canonical('PATCH', '/actions/'+identity, {'version':card['version'], 'status':jira_status(issue)})['item']
    link['jira_status'] = issue['fields']['status']['name']
    if persist:
        store.link(user, 'jira', link['resource'], link)
    return {'item':card, 'issue':issue, 'transitions':client.transitions(link['issue_key']), 'link':link}


def guard_status(user, identity, raw):
    """Jira-linked cards change state only through the verified connector flow."""
    if 'status' not in raw:
        return
    # Include disabled connectors and other users' links: a shared card cannot bypass Jira.
    with store.connection() as db:
        rows = db.execute("SELECT payload FROM connector_links WHERE provider='jira'").fetchall()
    import json
    if any(json.loads(row[0]).get('action_id') == identity for row in rows):
        current = action(identity)
        if raw['status'] != current['status']:
            raise HTTPException(409, 'Use the Jira controls on this action to change its status. Enable your connector if needed.')
