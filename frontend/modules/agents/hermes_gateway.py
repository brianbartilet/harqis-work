"""Server-only Hermes Runs transport. Never borrow public sharing credentials."""
import hashlib
import json
import os
import re
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', value):
        raise HTTPException(502, 'Hermes returned an invalid identity.')
    return value


class Gateway:
    def __init__(self):
        self.url = os.getenv('HARQIS_HERMES_URL', '').rstrip('/')
        self.key = os.getenv('HARQIS_HERMES_API_KEY', '').strip()
        parsed = urlsplit(self.url)
        if (not self.key or parsed.scheme not in {'http', 'https'} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path or (parsed.scheme == 'http' and parsed.hostname not in {'127.0.0.1', '::1', 'localhost'})):
            raise HTTPException(503, 'Configure the owner Hermes gateway URL and API key on the server.')
        self.host = parsed.hostname
        # Rotating credentials or changing hosts must never reuse an old admission/session.
        self.binding = hashlib.sha256((self.url + '\n' + self.key).encode()).hexdigest()

    def client(self):
        return httpx.Client(base_url=self.url, headers={'Authorization': 'Bearer ' + self.key},
                            timeout=httpx.Timeout(20, read=45), trust_env=False, follow_redirects=False)

    def request(self, method, path, payload=None, headers=None):
        try:
            with self.client() as client:
                response = client.request(method, path, json=payload, headers=headers)
            if not response.is_success:
                code = response.status_code if response.status_code in {404, 409, 429} else 502
                raise HTTPException(code, 'Hermes could not confirm this operation. Refresh to reconcile; do not resubmit as a new request.')
            if len(response.content) > 1_000_000:
                raise ValueError()
            return response.json()
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, 'Hermes is unavailable. The request may have been received; retry the same request.') from None

    def capabilities(self, *, require_readonly=False):
        data = self.request('GET', '/v1/capabilities')
        features = data.get('features', {}) if isinstance(data, dict) else {}
        if not isinstance(features, dict):
            raise HTTPException(502, 'Hermes returned invalid capabilities.')
        if not all(features.get(k) is True for k in ('run_submission', 'run_status')):
            raise HTTPException(503, 'This Hermes gateway does not support persistent runs.')
        admission = features.get('runs_idempotency', {})
        if (not isinstance(admission, dict) or admission.get('durable') is not True
                or admission.get('supported') is not True or type(admission.get('retention_seconds')) is not int
                or admission['retention_seconds'] < 3600):
            raise HTTPException(503, 'Hermes must support durable run admission with at least one hour of retention.')
        if require_readonly:
            # Current Hermes discovery excludes implicit default MCP servers.
            # This deployment contract is mandatory in addition to discovery:
            # platform_toolsets.api_server: [no_mcp], without other toolsets.
            if os.getenv('HARQIS_HERMES_TOOL_POLICY') != 'no-tools-no-mcp':
                raise HTTPException(503, 'Configure the Hermes API platform with no tools and no_mcp, then set HARQIS_HERMES_TOOL_POLICY=no-tools-no-mcp.')
            toolsets = self.request('GET', '/v1/toolsets')
            if isinstance(toolsets, dict):
                toolsets = toolsets.get('data')
            # Per-request tools=[] is not a Hermes execution policy. Require the
            # API platform to have no enabled toolsets, including MCP, at source.
            if not isinstance(toolsets, list) or any(not isinstance(t, dict) or t.get('enabled') is not False for t in toolsets):
                raise HTTPException(503, 'Disable all tools and MCP servers for the Hermes API platform before using frontend chat.')
        return {k: features.get(k) is True for k in ('run_events_sse', 'run_stop', 'run_steer')}

    def events(self, run_id):
        """Expose answer deltas only, never reasoning, tool arguments or raw errors."""
        try:
            with self.client() as client, client.stream('GET', '/v1/runs/' + identifier(run_id) + '/events') as response:
                response.raise_for_status()
                event, data = '', []
                for line in response.iter_lines():
                    if line.startswith(':'):
                        yield ': keepalive\n\n'
                    elif line.startswith('event:'):
                        event = line[6:].strip()
                    elif line.startswith('data:'):
                        data.append(line[5:].strip())
                        if sum(map(len, data)) > 100_000:
                            raise ValueError()
                    elif not line:
                        if event == 'message.delta' and data:
                            value = json.loads('\n'.join(data))
                            delta = value.get('delta', value.get('text', ''))
                            if isinstance(delta, str):
                                yield 'event: delta\ndata: ' + json.dumps({'text': delta[:20000]}) + '\n\n'
                        elif event.startswith('run.'):
                            yield 'event: refresh\ndata: {}\n\n'
                            if event in {'run.completed', 'run.failed', 'run.cancelled', 'run.interrupted'}:
                                return
                        event, data = '', []
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            yield 'event: refresh\ndata: {}\n\n'
