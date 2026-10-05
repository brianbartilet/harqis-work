"""Typed canonical timeline API operations."""
from __future__ import annotations

from apps.hfl_corpus.references.web.api.extended import ApiServiceHflCorpusExtended


class ApiServiceHflCorpusTimeline(ApiServiceHflCorpusExtended):

    def get_timeline_source(self, path: str, entry_id: str) -> dict:
        """Validate and read the title/date of unprotected entry evidence.

        Args:
            path: Corpus-relative Markdown document path.
            entry_id: Stable HFL entry ID.
        """
        return self._json('GET', 'timeline/source', params=dict(path=path, entry_id=entry_id))

    def get_timeline_evidence(self, path: str, entry_id: str) -> dict:
        """Return the validated evidence navigation link without following its redirect.

        Args:
            path: Corpus-relative Markdown document path.
            entry_id: Stable HFL entry ID.
        """
        response = self._raw_request('GET', 'timeline/evidence', params=dict(path=path, entry_id=entry_id), allow_redirects=False)
        if response.status_code != 303 or not response.headers.get('location', '').startswith('/hfl-corpus/document/'):
            raise ValueError('Expected a validated corpus evidence link.')
        return {'location': response.headers['location'], 'status_code': 303}

    def list_timeline_items(
        self,
        closed: bool = False,
        offset: int = 0,
        include_closed: bool = False,
        recent_dismissed: bool = False,
        query: str = '',
        source: str = '',
        date_field: str = 'created',
        date_from: str = '',
        date_to: str = '',
        rolling: int = 0,
        scope: dict | None = None,
    ) -> dict:
        """List up to 500 scoped agenda items with board positions and due-state grouping.

        Args:
            closed: Closed.
            offset: Nonnegative pagination offset.
            include_closed: Include closed.
            recent_dismissed: Recent dismissed.
            query: Search text; empty means no text filter.
            source: Source.
            date_field: Date field.
            date_from: Date from.
            date_to: Date to.
            rolling: Rolling.
            scope: Optional combined-view object with any/all filter clauses.
        """
        return self._json('GET', 'timeline/items', params=dict(closed=closed, offset=offset, include_closed=include_closed, recent_dismissed=recent_dismissed, q=query, source=source, date_field=date_field, date_from=date_from, date_to=date_to, rolling=rolling, scope=scope))

    def update_timeline_order(self, status: str, items: list[dict]) -> dict:
        """Reorder a status column with item version checks. Destructive: writes remote state.

        Args:
            status: Status.
            items: Ordered objects containing id and version; use the latest versions.
        """
        return self._json('PUT', 'timeline/items/order', payload=dict(status=status, items=items))

    def create_timeline_item(self, item: dict) -> dict:
        """Create/adopt an agenda item. May configure agent execution if explicitly requested. Destructive: writes remote state.

        Args:
            item: Action fields: request_id UUID, title, expected_outcome, source, suggestion_id, review_date, due_date, prompt, notes, checklists, matrix, agent_enabled, board_ids (optional active board IDs). Server validates; omission preserves normal defaults.
        """
        return self._json('POST', 'timeline/items', payload=item)


    def create_checklist_action(self, followup_id: str, version: int, checklist_id: str, item_id: str, request_id: str, item: dict) -> dict:
        """Create an action and tick its source checklist item atomically. Destructive: writes remote state.

        Args:
            followup_id: Parent action ID.
            version: Latest parent version; stale writes return 409 without creating an action.
            checklist_id: Stable source checklist ID.
            item_id: Stable source item ID.
            request_id: UUID for retry-safe creation; reuse with the same payload after an uncertain response.
            item: New action fields including title and expected_outcome. Agent execution is always disabled.
        """
        return self._json('POST', f'timeline/items/{self._segment(followup_id)}/checklist-action', payload=dict(version=version, checklist_id=checklist_id, item_id=item_id, request_id=request_id, item=item))

    def update_timeline_item(self, followup_id: str, version: int, changes: dict) -> dict:
        """Update an agenda item using its latest version. Can alter scheduling; completion writes a receipt. Destructive: writes remote state.

        Args:
            followup_id: Followup id.
            version: Latest object version; stale writes return 409. Read before retrying.
            changes: Action fields to change; status, dates, title, expected_outcome, prompt, notes, checklists, matrix, agent_enabled, board_ids (optional active board IDs). Do not supply internal _agent_actor attribution.
        """
        if '_agent_actor' in changes:
            raise ValueError('Internal worker attribution is not accepted by owner tools.')
        return self._json('PATCH', f'timeline/items/{self._segment(followup_id)}', payload={**changes, 'version': version})

    def get_timeline_item(self, followup_id: str) -> dict:
        """Read the current agenda item and version.

        Args:
            followup_id: Followup id.
        """
        return self._json('GET', f'timeline/items/{self._segment(followup_id)}')

    def get_timeline_history(self, followup_id: str) -> dict:
        """Read immutable agenda revisions and rendered completion notes.

        Args:
            followup_id: Followup id.
        """
        return self._json('GET', f'timeline/items/{self._segment(followup_id)}/history')

    def get_timeline_markers(
        self,
        query: str = '',
        source: str = '',
        date_field: str = 'created',
        date_from: str = '',
        date_to: str = '',
        rolling: int = 0,
        scope: dict | None = None,
    ) -> dict:
        """Read scoped action date markers and aggregate statuses.

        Args:
            query: Search text; empty means no text filter.
            source: Source.
            date_field: Date field.
            date_from: Date from.
            date_to: Date to.
            rolling: Rolling.
            scope: Optional combined-view object with any/all filter clauses.
        """
        return self._json('GET', 'timeline/markers', params=dict(q=query, source=source, date_field=date_field, date_from=date_from, date_to=date_to, rolling=rolling, scope=scope))

    def get_timeline_period(
        self,
        start: str,
        end: str,
        query: str = '',
        source: str = '',
        date_field: str = 'created',
        date_from: str = '',
        date_to: str = '',
        rolling: int = 0,
        scope: dict | None = None,
    ) -> dict:
        """Read agenda items, suggestions, receipts and exploration state for 1–31 inclusive days.

        Args:
            start: Inclusive start date, YYYY-MM-DD.
            end: Inclusive end date, YYYY-MM-DD.
            query: Search text; empty means no text filter.
            source: Source.
            date_field: Date field.
            date_from: Date from.
            date_to: Date to.
            rolling: Rolling.
            scope: Optional combined-view object with any/all filter clauses.
        """
        return self._json('GET', 'timeline/period', params=dict(start=start, end=end, q=query, source=source, date_field=date_field, date_from=date_from, date_to=date_to, rolling=rolling, scope=scope))

    def update_timeline_suggestion_dismiss(self, sid: str) -> dict:
        """Dismiss an idea/suggestion. Destructive: writes remote state.

        Args:
            sid: Sid.
        """
        return self._json('POST', f'timeline/suggestions/{self._segment(sid)}/dismiss')

    def create_timeline_exploration(self, start: str, end: str) -> dict:
        """Schedule AI exploration for 1–31 days ending today or earlier; may incur model usage. Destructive: writes remote state.

        Args:
            start: Inclusive start date, YYYY-MM-DD.
            end: Inclusive end date, YYYY-MM-DD.
        """
        return self._json('POST', 'timeline/explore', payload=dict(start=start, end=end))
