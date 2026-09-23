"""Shared transport for the typed canonical frontend service methods.

Endpoints are chosen by service methods, never supplied as URLs by tool callers.
Redirects are deliberately not followed: owner credentials must stay at the
configured origin and HTML login pages must not masquerade as API results.
"""
from contextlib import ExitStack
import json
from pathlib import Path
from urllib.parse import quote

from apps.hfl_corpus.references.web.base_api_service import BaseApiServiceHflCorpus


class ApiServiceHflCorpusExtended(BaseApiServiceHflCorpus):
    @staticmethod
    def _segment(value: str | int) -> str:
        value = str(value)
        if not value or value in {'.', '..'} or any(c in value for c in '/\\\x00\r\n'):
            raise ValueError('Expected a single nonempty resource ID.')
        return quote(value, safe='')

    @staticmethod
    def _params(values: dict) -> dict:
        return {
            key: (json.dumps(value, separators=(',', ':')) if isinstance(value, dict)
                  else str(value).lower() if isinstance(value, bool) else value)
            for key, value in values.items() if value is not None
        }

    def _json(self, method: str, path: str, *, params: dict | None = None,
              payload: dict | None = None) -> dict:
        response = self._raw_request(method, path, params=self._params(params or {}),
                                     json=payload, allow_redirects=False)
        if response.is_redirect:
            raise ValueError('Unexpected API redirect; check the configured canonical frontend origin.')
        if response.status_code == 204:
            return {'status_code': 204}
        if 'application/json' not in response.headers.get('content-type', '').lower():
            raise ValueError('Expected a JSON API response; check the configured frontend origin.')
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError('Expected an API object response.')
        return result

    def _upload_files(self, path: str, file_paths: list[str]) -> dict:
        paths = [Path(p).expanduser().resolve() for p in file_paths]
        if not 1 <= len(paths) <= 50 or any(not p.is_file() or p.stat().st_size > 500 * 1024 * 1024 for p in paths):
            raise ValueError('Choose 1–50 regular files, at most 500 MB each.')
        with ExitStack() as stack:
            files = [('files', (p.name, stack.enter_context(p.open('rb')), 'application/octet-stream')) for p in paths]
            response = self._raw_request('POST', path, files=files, allow_redirects=False)
            if response.is_redirect or 'application/json' not in response.headers.get('content-type', '').lower():
                raise ValueError('Expected a JSON upload response.')
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError('Expected an API object response.')
            return result
