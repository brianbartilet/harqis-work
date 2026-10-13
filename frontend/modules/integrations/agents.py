"""Agent adapters prepare durable action-backed application development sessions."""
import re
import uuid
from dataclasses import dataclass
from fastapi import HTTPException
from modules.applications.inventory import get_application
from modules.integrations import service, store

@dataclass(frozen=True)
class AgentAdapter:
    key: str
    name: str
    available: bool = False
    workspace_route: str = ''

    def workspace_url(self, action_id):
        if not self.available:
            raise HTTPException(422, self.name+' sessions are not installed on this host.')
        return self.workspace_route+action_id


# Future adapters supply a transport/workspace rather than treating a model
# provider (agent_provider) as a CLI runtime. Unsupported engines never dispatch.
ADAPTERS = {a.key:a for a in [AgentAdapter('hermes','Hermes',True,'/hfl-corpus/actions?integration_agent='),
                             AgentAdapter('codex','Codex'), AgentAdapter('claude','Claude')]}
AGENTS = [{'id':a.key, 'name':a.name, 'available':a.available} for a in ADAPTERS.values()]
SKILLS = ['create-new-service-app', 'create-new-mcp', 'create-new-workflow', 'create-new-n8n-workflow']


def prepare(user, raw):
    selected = raw.get('agent', 'hermes')
    if not isinstance(selected, str) or type(raw.get('create', False)) is not bool:
        raise HTTPException(422, 'Choose an agent and a boolean creation mode.')
    adapter = ADAPTERS.get(selected)
    if adapter is None or not adapter.available:
        raise HTTPException(422, 'Only Hermes sessions are available on this host.')
    name = raw.get('name', '')
    description = raw.get('description', '')
    if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_]{1,63}', name):
        raise HTTPException(422, 'Use 2–64 lower-case letters, numbers, or underscores; start with a letter.')
    if not isinstance(description, str) or len(description) > 3000:
        raise HTTPException(422, 'Keep the description within 3,000 characters.')
    exists = get_application(name)
    if raw.get('create') and exists:
        raise HTTPException(409, 'This application already exists. Open its agent section.')
    if not raw.get('create') and not exists:
        raise HTTPException(404, 'Application not found.')
    resource = 'application:'+name
    previous = next((x for x in store.links(user, 'agent') if x['resource'] == resource), None)
    if previous and previous.get('action_id'):
        return service.action(previous['action_id'])
    creation = (previous or {}).get('creation') or {
        'request_id':str(uuid.uuid5(uuid.NAMESPACE_URL, 'integration-agent:'+user+':'+name)),
        'title':('Build' if raw.get('create') else 'Maintain')+' integration: '+name,
        'expected_outcome':'A reviewed and tested application integration in an isolated branch.',
        'body':description,
        'prompt':('Work on apps/'+name+' in the isolated repository checkout. '+
                  'Initial README description:\n'+description+'\n\n'+
                  'Read the existing integration conventions and applicable skill instructions. Relevant skills: '+
                  ', '.join('$'+s for s in SKILLS)+'. Clarify missing API requirements before implementing. '+
                  'Do not copy frontend connector credentials or change workflow credentials. Do not deploy, merge, or push without an explicit instruction.')}
    store.link(user, 'agent', resource, {'creation':creation})
    card = service.canonical('POST', '/actions', creation)['item']
    store.link(user, 'agent', resource, {'action_id':card['id'], 'creation':creation})
    return card
