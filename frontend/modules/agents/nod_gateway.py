"""Nod self-host connection scaffold; no conversation or task submission.

Contract: n8n-io/nod src/server/access.ts and app.ts (2026-11-12).
GET /api/health is authenticated with the self-host NOD_AUTH_TOKEN.
"""
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException


class NodGateway:
    def __init__(self, *, url, key):
        self.url = url.strip().rstrip('/')
        self.key = key.strip()
        try:
            parsed = urlsplit(self.url)
            port = parsed.port
            valid = (parsed.scheme in {'http', 'https'} and parsed.hostname
                     and not any((parsed.username, parsed.password, parsed.path, parsed.query, parsed.fragment))
                     and (port is None or port > 0)
                     and (parsed.scheme == 'https' or parsed.hostname in {'localhost', '127.0.0.1', '::1'}))
        except ValueError:
            valid = False
        if not valid or not self.key or any(c.isspace() for c in self.key):
            raise HTTPException(422, 'Enter a Nod server origin (HTTPS or loopback HTTP) and its access token.')

    def client(self):
        return httpx.Client(base_url=self.url, headers={'Authorization': 'Bearer ' + self.key},
                            timeout=10, trust_env=False, follow_redirects=False)

    def capabilities(self):
        try:
            with self.client() as client:
                response = client.get('/api/health')
            if response.status_code in {401, 403}:
                raise HTTPException(502, 'Nod rejected access. Check the server token and allowed host configuration.')
            if response.status_code != 200 or len(response.content) > 4096 or response.json() != {'ok': True}:
                raise ValueError()
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, 'Nod health check failed. Check the server address, tunnel and Nod version.') from None
        return {'health': True, 'chat': False, 'run_submission': False, 'run_status': False,
                'run_events_sse': False, 'run_stop': False, 'run_steer': False}
