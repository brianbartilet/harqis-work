"""Bounded provider requests using explicit connector credentials, never host config."""
import re
import time
from urllib.parse import quote

import httpx
from fastapi import HTTPException


def segment(value):
    return quote(str(value), safe='')


def repository(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value) or any(p in {'.','..'} for p in value.split('/')):
        raise HTTPException(422, 'Choose a repository as owner/name.')
    return value


def branch(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 200 or any(x in value for x in ['..','@{','//','\\']) or re.search(r'[\s~^:?*\[\x00-\x1f\x7f]', value) or any(p.startswith('.') or p.endswith(('.', '.lock')) for p in value.split('/')) or value.startswith('/') or value.endswith('/') or value == '@':
        raise HTTPException(422, 'Enter a valid Git branch name.')
    return value


def credentials(provider, raw):
    if provider == 'claude':
        from modules.integrations.claude import credentials as local_credentials
        return local_credentials(raw)
    if provider == 'codex':
        from modules.integrations.codex import credentials as local_credentials
        return local_credentials(raw)
    token = raw.get('token', '')
    if not isinstance(token, str) or not 1 <= len(token.strip()) <= 4096 or any(ord(c) < 32 for c in token):
        raise HTTPException(422, 'Enter an API token.')
    result = {'token': token.strip()}
    if provider == 'nod':
        from modules.agents.nod_gateway import NodGateway
        if not isinstance(raw.get('site'), str):
            raise HTTPException(422, 'Enter a Nod server URL.')
        result['site'] = NodGateway(url=raw['site'], key=result['token']).url
    if provider == 'n8n':
        from modules.integrations.n8n import site, browser_origin
        result['site'] = site(raw.get('site'))
        result['public_url'] = browser_origin(raw.get('public_url', ''))
        mcp = raw.get('mcp_token', '')
        if not isinstance(mcp, str) or len(mcp) > 4096 or any(ord(c) < 32 for c in mcp):
            raise HTTPException(422, 'Invalid MCP token.')
        result['mcp_token'] = mcp.strip()
    if provider == 'jira':
        if any(not isinstance(raw.get(key, ''), str) for key in ('site', 'email', 'cloud_id')):
            raise HTTPException(422, 'Site, email, and cloud ID must be text.')
        site = raw.get('site', '').strip().rstrip('/').lower()
        if not re.fullmatch(r'https://[a-z0-9][a-z0-9-]*\.atlassian\.net', site):
            raise HTTPException(422, 'Use your HTTPS Jira Cloud site: https://company.atlassian.net.')
        email = raw.get('email', '').strip()
        if not re.fullmatch(r'[^\s@:]+@[^\s@]+\.[^\s@]+', email) or len(email) > 254:
            raise HTTPException(422, 'Enter your Atlassian account email.')
        cloud_id = raw.get('cloud_id', '').strip()
        if cloud_id and not re.fullmatch(r'[0-9a-fA-F-]{36}', cloud_id):
            raise HTTPException(422, 'Enter a valid cloud ID for a scoped API token.')
        result.update(site=site, email=email, cloud_id=cloud_id)
    return result


class Provider:
    def __new__(cls, provider, credentials):
        if provider == 'claude':
            from modules.integrations.claude import Claude
            return Claude(credentials)
        if provider == 'codex':
            from modules.integrations.codex import Codex
            return Codex(credentials)
        if provider == 'nod':
            from modules.integrations.nod import Nod
            return Nod(credentials)
        if provider == 'n8n':
            from modules.integrations.n8n import N8n
            return N8n(credentials)
        return super().__new__(cls)
    def __init__(self, provider, credentials):
        self.provider, self.credentials = provider, credentials

    def request(self, method, path, *, params=None, json=None, missing=False):
        c = self.credentials
        if self.provider == 'github':
            base = 'https://api.github.com'
            headers = {'Authorization': 'Bearer '+c['token'], 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
            auth = None
        else:
            base = ('https://api.atlassian.com/ex/jira/'+c['cloud_id']) if c.get('cloud_id') else c['site']
            headers, auth = {'Accept': 'application/json'}, (c['email'], c['token'])
        try:
            with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
                response = client.request(method, base+path, headers=headers, auth=auth, params=params, json=json)
        except httpx.HTTPError:
            raise HTTPException(502, 'Provider unavailable. Refresh to reconcile the result before retrying.') from None
        if response.status_code == 404 and missing:
            return None
        if not response.is_success:
            # Never expose provider response bodies: they may echo submitted credentials.
            messages = {401: 'Token expired, revoked, or invalid. Reconnect.', 403: 'Access denied. Check token permissions, organization approval, and account access.',
                        404: 'Resource unavailable or not permitted.', 429: 'Provider rate limit reached. Wait before retrying.',
                        400: 'Provider rejected this operation. Check required fields and workflow rules.',
                        422: 'Provider rejected the operation. Check for an existing branch/PR, missing commits, or invalid fields.'}
            retry_headers = None
            if response.status_code in {403, 429}:
                delay = response.headers.get('Retry-After', '')
                reset = response.headers.get('X-RateLimit-Reset', '')
                if not delay.isdigit() and response.headers.get('X-RateLimit-Remaining') == '0' and reset.isdigit():
                    delay = str(max(1, int(reset) - int(time.time())))
                if delay.isdigit() or response.status_code == 429:
                    retry_headers = {'Retry-After': str(max(1, min(3600, int(delay) if delay.isdigit() else 300)))}
            raise HTTPException(502 if response.status_code >= 500 else response.status_code,
                                messages.get(response.status_code, 'Provider request failed. Refresh before retrying.'),
                                headers=retry_headers)
        if response.status_code == 204:
            return {}
        try:
            return response.json()
        except ValueError:
            raise HTTPException(502, 'Provider returned an unreadable response.') from None

    def test(self):
        data = self.request('GET', '/user' if self.provider == 'github' else '/rest/api/3/myself')
        return {'account': data.get('login') or data.get('displayName'), 'account_id': str(data.get('id') or data.get('accountId'))}

    def issue(self, key):
        return self.request('GET', '/rest/api/3/issue/'+segment(key), params={'fields':'summary,status,assignee,project'})

    def transitions(self, key):
        return self.request('GET', '/rest/api/3/issue/'+segment(key)+'/transitions', params={'expand':'transitions.fields'})['transitions']


def jira_status(issue):
    return {'new':'active', 'indeterminate':'in_progress', 'done':'done'}.get(issue['fields']['status']['statusCategory']['key'], 'open')
