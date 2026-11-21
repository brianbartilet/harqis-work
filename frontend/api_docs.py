"""Owner-only, same-origin documentation for the complete HARQIS HTTP surface."""
from copy import deepcopy

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from auth import get_current_user
from modules.hfl_shares.security import make_csrf_token
from web import page_context, require_user, templates

router = APIRouter()
METHODS = {'get', 'post', 'put', 'patch', 'delete', 'head', 'options'}
GROUPS = [
    ('Getting started', 'Health, sign-in and diagnostics.'),
    ('Agents · Fleet', 'Profiles, specializations, connections and execution defaults.'),
    ('Agents · Conversations', 'Gateway conversations, messages and run controls.'),
    ('Agents · Sessions & workers', 'Action bridge sessions and worker protocol. Worker commands require a separate bridge token.'),
    ('Workflows', 'Registered Celery workflows, dispatch and task status. Triggering submits real work.'),
    ('Corpus · Entries & search', 'Capture, retrieve and search the Activity Corpus.'),
    ('Corpus · Actions & planning', 'Actions, ideas, boards, goals, categories and pins.'),
    ('Activity · Quick Notes', 'Owner checklist notes, Space links, ordering and lifecycle operations.'),
    ('Corpus · Entities', 'Entity profiles, relationships, merges and resolution.'),
    ('Corpus · Sources & synchronization', 'Source ingestion, connector synchronization and execution receipts.'),
    ('Activity · Timeline & views', 'Dashboard activity, timeline editing and view preferences.'),
    ('Integrations', 'Connected services, discovery and provider-specific operations.'),
    ('Files', 'File inventory, attachments and file packages.'),
    ('Sharing · Owner', 'Create and manage activity shares. Some operations use form bodies.'),
    ('Sharing · Guest', 'Recipient access and guest sessions. Use the intended share link to establish access first.'),
    ('Second Brain · HUD & chat', 'Dashboard widgets, context, settings and assistant interactions.'),
    ('Roles & Spaces', 'Roles, workspace organization and profiles.'),
    ('Git Forks', 'Fleet scans, synchronization, tests and deployments.'),
    ('Settings & browser forms', 'Owner settings and browser-facing HTML/form routes.'),
]


def group_for(path):
    if path in {'/health', '/login', '/logout', '/debug/config'}:
        return 'Getting started'
    if path.startswith('/api/hfl-agent') or path.startswith('/hfl-corpus/agent-bridge'):
        return 'Agents · Sessions & workers'
    if path.startswith('/agents'):
        if '/conversations' in path or '/messages' in path:
            return 'Agents · Conversations'
        return 'Agents · Fleet'
    if path.startswith(('/workflows', '/tasks/')):
        return 'Workflows'
    if path.startswith(('/api/hfl/entities', '/hfl-corpus/entities', '/knowledge')):
        return 'Corpus · Entities'
    if path.startswith('/api/hfl/'):
        section = path.split('/')[3]
        if section in {'actions', 'timeline', 'ideas', 'boards', 'goals', 'categories', 'pins', 'roles', 'workspaces'}:
            return 'Corpus · Actions & planning'
        if section in {'entries', 'documents', 'search', 'tree', 'matches', 'activity', 'curated-feed', 'stats'}:
            return 'Corpus · Entries & search'
        return 'Corpus · Sources & synchronization'
    if path.startswith('/hfl-corpus/quick-notes'):
        return 'Activity · Quick Notes'
    if path.startswith('/hfl-corpus'):
        return 'Activity · Timeline & views'
    if path.startswith(('/integrations', '/applications')):
        return 'Integrations'
    if path.startswith(('/share/', '/file-share/')):
        return 'Sharing · Guest'
    if path.startswith('/sharing'):
        return 'Sharing · Owner'
    if path.startswith('/files'):
        return 'Files'
    if path.startswith('/second-brain'):
        return 'Second Brain · HUD & chat'
    if path.startswith(('/roles', '/spaces', '/profile')):
        return 'Roles & Spaces'
    if path.startswith('/git-forks'):
        return 'Git Forks'
    return 'Settings & browser forms'


def consolidated_schema(app):
    # Decorate a copy: never alter the runtime or standalone corpus contracts.
    schema = deepcopy(app.openapi())
    schema['info'] = {
        'title': 'HARQIS API reference', 'version': '1.0.0',
        'description': (
            'All schema-visible HARQIS dashboard and Corpus routes, grouped by capability. '
            'Requests run against this dashboard origin, including the mounted Corpus API. '
            'Static assets and intentionally hidden routes are excluded. External services such as '
            'Nod, Hermes and n8n are represented by HARQIS connector endpoints, not their upstream APIs.\n\n'
            '**Testing:** start with GET /health and GET /agents/api/catalogue. '
            'Your signed-in dashboard session is reused; owner write requests receive a CSRF token automatically. '
            'For Corpus routes, use Authorize → HTTPBearer with your existing HFL corpus API token. '
            'Worker routes require BridgeToken instead. Tokens are not supplied by this page or persisted across reloads. '
            'Try it out sends real requests. Mutation and dispatch endpoints change live data. '
            'HTML/form and guest endpoints retain their original response and authentication behavior.'
        ),
    }
    schema['servers'] = [{'url': '/', 'description': 'Current HARQIS host (same origin)'}]
    schema['tags'] = [{'name': name, 'description': description} for name, description in GROUPS]
    schemes = schema.setdefault('components', {}).setdefault('securitySchemes', {})
    schemes['OwnerSession'] = {'type': 'apiKey', 'in': 'cookie', 'name': 'session',
        'description': 'Sign in through /login. Swagger reuses the HttpOnly browser cookie; do not paste it here.'}
    schemes['BridgeToken'] = {'type': 'http', 'scheme': 'bearer',
        'description': 'Existing HFL_AGENT_BRIDGE_TOKEN for worker protocol calls; not the corpus API token.'}
    schemes.setdefault('HTTPBearer', {'type': 'http', 'scheme': 'bearer'})['description'] = (
        'Existing HFL_CORPUS_API_TOKEN. Enter only the token, without the Bearer prefix.')
    for path, methods in schema['paths'].items():
        for method, operation in methods.items():
            if method not in METHODS:
                continue
            operation['tags'] = [group_for(path)]
            # Existing OpenAPI security is authoritative. These legacy handlers
            # perform manual authentication, which FastAPI cannot infer.
            if path.startswith('/api/hfl-agent/'):
                operation['security'] = [{'BridgeToken': []}]
            elif path.startswith('/api/hfl/entities'):
                operation['security'] = [{'OwnerSession': []}, {'HTTPBearer': []}]
            elif path.startswith('/api/hfl/'):
                operation.setdefault('security', [{'HTTPBearer': []}])
            elif path.startswith(('/share/', '/file-share/')):
                operation['description'] = (operation.get('description', '') + '\n\n'
                    'Recipient access rules apply. Open the share URL to establish the required guest session; '
                    'an owner login does not substitute for recipient authorization.').strip()
            elif path not in {'/health', '/login'}:
                operation.setdefault('security', [{'OwnerSession': []}])
            if method not in {'get', 'head', 'options'}:
                operation['description'] = (operation.get('description', '') + '\n\n'
                    '**Live request:** Execute submits this operation to the running host. '
                    'Review the body and target before submitting.').strip()
            body = operation.get('requestBody', {}).get('content', {})
            if 'text/html' in operation.get('responses', {}).get('200', {}).get('content', {}):
                operation['description'] = (operation.get('description', '') + '\n\n'
                    'Returns HTML for the browser interface, not JSON.').strip()
            if method == 'post' and path in {'/agents/api/items', '/agents/api/items/{identity}'}:
                example = ({'name': 'Workflow operator', 'runtime': 'hermes', 'classification': 'workflows',
                    'description': 'Runs existing HARQIS workflows on request.',
                    'instructions': 'Run only requested registered workflows; report the task ID and verified result.',
                    'workflows': [], 'triggers': [], 'active': True}
                    if path.endswith('/items') else {'version': 1, 'description': 'Updated agent description.'})
                body.setdefault('application/json', {'schema': {'type': 'object'}})['examples'] = {
                    'profile': {'summary': 'Create a workflow operator' if path.endswith('/items') else 'Update using the current version', 'value': example}}
                operation['description'] += ('\n\nWorkflow IDs come from GET /agents/api/catalogue. '
                    'Linking workflows does not execute them. Updates require the current version from GET /agents/api/items.')
    return schema


@router.get('/docs', include_in_schema=False)
def documentation(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, 'api_docs.html', page_context(
        request, user, 'api_docs', docs_csrf=make_csrf_token(user)))


@router.get('/openapi.json', include_in_schema=False)
def openapi(request: Request):
    if not get_current_user(request):
        raise HTTPException(401, 'Sign in to view the API reference.')
    return JSONResponse(consolidated_schema(request.app))
