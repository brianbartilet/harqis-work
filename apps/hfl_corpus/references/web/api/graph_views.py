"""Typed canonical graph views API operations."""
from __future__ import annotations

from apps.hfl_corpus.references.web.api.extended import ApiServiceHflCorpusExtended


class ApiServiceHflCorpusGraphViews(ApiServiceHflCorpusExtended):

    def list_graph_views(self) -> dict:
        """List saved graph views and the selected view.
        """
        return self._json('GET', 'graph-views')

    def create_graph_view(self, name: str, state: dict) -> dict:
        """Create and select a named graph view. Destructive: writes remote state.

        Args:
            name: Name.
            state: View state: density, query, sources, since/until, rolling, shared, group, enabled, focus, layout. Server validates fields.
        """
        return self._json('POST', 'graph-views', payload=dict(name=name, state=state))

    def update_graph_view(self, identity: str, name: str, state: dict, revision: int) -> dict:
        """Replace a saved graph view using its latest revision. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            name: Name.
            state: Complete graph view state, including layout if it must be retained.
            revision: Latest saved-view revision; stale writes return 409.
        """
        return self._json('PUT', f'graph-views/{self._segment(identity)}', payload=dict(name=name, state=state, revision=revision))

    def update_graph_view_selection(self, identity: str) -> dict:
        """Select an existing saved graph view. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
        """
        return self._json('POST', f'graph-views/{self._segment(identity)}/select')

    def delete_graph_view(self, identity: str, revision: int) -> dict:
        """Delete a graph view with an optimistic revision check. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            revision: Latest saved-view revision; stale writes return 409.
        """
        return self._json('DELETE', f'graph-views/{self._segment(identity)}', params=dict(revision=revision))
