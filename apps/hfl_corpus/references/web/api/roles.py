"""Canonical bearer-authenticated Facets operations (API resource: roles)."""
from __future__ import annotations

from apps.hfl_corpus.references.web.api.extended import ApiServiceHflCorpusExtended


class ApiServiceHflCorpusRoles(ApiServiceHflCorpusExtended):
    def list_roles(self) -> dict:
        """List private facets, linked Spaces, analysis runs, and palette."""
        return self._json('GET', 'roles')

    def create_role(self, payload: dict) -> dict:
        """Create a facet. Payload: name, color, soul, workspace_ids, entity_ids,
        archived; revision defaults to zero. Server validates all fields.
        """
        return self._json('POST', 'roles', payload=payload)

    def update_role(self, identity: str, payload: dict) -> dict:
        """Replace editable facet fields using the latest revision in payload.
        Include name, color, soul, workspace_ids, entity_ids and archived to
        preserve them; omitted fields take server defaults. Stale writes: 409.
        """
        return self._json('PUT', f'roles/{self._segment(identity)}', payload=payload)

    def create_role_audit(self, run_id: str) -> dict:
        """Run private facet analysis with a stable retry ID. Persists observations
        and an HFL report; does not publish personal context into existing shares.
        """
        return self._json('POST', 'roles/audit/run', payload={'run_id': run_id})
