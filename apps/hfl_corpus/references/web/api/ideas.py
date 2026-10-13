"""Typed canonical ideas API operations."""
from __future__ import annotations

from apps.hfl_corpus.references.web.api.extended import ApiServiceHflCorpusExtended


class ApiServiceHflCorpusIdeas(ApiServiceHflCorpusExtended):

    def list_item_connection_options(self, query: str = '', offset: int = 0) -> dict:
        """Search visible ideas/actions available for linking, in pages of 50."""
        return self._json('GET', 'timeline/ideas/item-connection-options',
                          params=dict(query=query, offset=offset))

    def update_item_connection(self, payload: dict) -> dict:
        """Create, update or remove a shared manual link (remote write)."""
        return self._json('POST', 'timeline/ideas/item-connections', payload=payload)

    def get_ideas_snapshot(self) -> dict:
        """Read ideas, maps, links, goals and visible graph context.
        """
        return self._json('GET', 'timeline/ideas/snapshot')

    def get_connection_availability(self) -> dict:
        """Read available object connection choices.
        """
        return self._json('GET', 'timeline/ideas/connection-availability')

    def get_action_connections(self, identity: str) -> dict:
        """Read an action’s graph connections.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
        """
        return self._json('GET', f'timeline/ideas/actions/{self._segment(identity)}/connections')

    def get_date_connections(self, identity: str) -> dict:
        """Read a date pin’s graph connections.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
        """
        return self._json('GET', f'timeline/ideas/dates/{self._segment(identity)}/connections')

    def get_idea_connections(self, identity: str) -> dict:
        """Read an idea's graph connections.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
        """
        return self._json('GET', f'timeline/ideas/ideas/{self._segment(identity)}/connections')

    def list_boards(self) -> dict:
        """Read board metadata, goals and the color palette without scanning the corpus.
        """
        return self._json('GET', 'timeline/ideas/boards')

    def get_board_context(self) -> dict:
        """Read active boards with all permitted member objects and connections."""
        return self._json('GET', 'timeline/ideas/board-context')

    def list_reuse_options(self, query: str = '', page: int = 1) -> dict:
        """Search actions and ideas available for independent copying."""
        return self._json('GET', 'timeline/ideas/reuse/options', params=dict(query=query, page=page))

    def list_board_ideas(self, dismissed: bool = False) -> dict:
        """List visible ideas available to boards, optionally including dismissed ideas."""
        return self._json('GET', 'timeline/ideas/reuse/board-ideas', params={'dismissed': '1' if dismissed else '0'})

    def get_clone_draft(self, kind: str, identity: str) -> dict:
        """Preview an independent action or idea copy without saving it."""
        return self._json('GET', f'timeline/ideas/reuse/clone/{self._segment(kind)}/{self._segment(identity)}')

    def create_clone(self, kind: str, identity: str, request_id: str, source_version: int,
                     item: dict, attachments: list[str] | None = None) -> dict:
        """Create a copy using a caller UUID and the source revision. Writes remote state."""
        return self._json('POST', f'timeline/ideas/reuse/clone/{self._segment(kind)}/{self._segment(identity)}',
                          payload=dict(request_id=request_id, source_version=source_version, item=item, attachments=attachments or []))

    def create_list_copy(self, kind: str, identity: str, request_id: str, version: int, checklist: dict) -> dict:
        """Copy a checklist into an action or idea at the expected revision. Writes remote state."""
        return self._json('POST', 'timeline/ideas/reuse/copy-list',
                          payload=dict(kind=kind, identity=identity, request_id=request_id, version=version, checklist=checklist))

    def create_map_paste(self, identity: str, request_id: str, version: int, source_board: str,
                         source_version: int, selected: list[str]) -> dict:
        """Paste selected objects between versioned boards. Writes remote state."""
        return self._json('POST', f'timeline/ideas/maps/{self._segment(identity)}/paste',
                          payload=dict(request_id=request_id, version=version, source_board=source_board,
                                       source_version=source_version, selected=selected))

    def get_list(self, identity: str) -> dict:
        """Read a standalone or owner-linked checklist entity."""
        return self._json('GET', f'timeline/ideas/lists/{self._segment(identity)}')

    def create_list(self, request_id: str, checklist: dict) -> dict:
        """Create a standalone checklist with a caller-generated UUID. Writes remote state."""
        return self._json('POST', 'timeline/ideas/lists', payload=dict(request_id=request_id, checklist=checklist))

    def update_list(self, identity: str, version: int, checklist: dict) -> dict:
        """Update a standalone or owner-linked checklist at its expected revision. Writes remote state."""
        return self._json('PATCH', f'timeline/ideas/lists/{self._segment(identity)}', payload=dict(version=version, checklist=checklist))

    def update_board_order(self, ids: list[str]) -> dict:
        """Persist board ordering. Destructive: writes remote state.

        Args:
            ids: Ids.
        """
        return self._json('PUT', 'timeline/ideas/boards/order', payload=dict(ids=ids))

    def update_goal_order(self, ids: list[str]) -> dict:
        """Persist goal ordering. Destructive: writes remote state.

        Args:
            ids: Ids.
        """
        return self._json('PUT', 'timeline/ideas/goals/order', payload=dict(ids=ids))

    def get_goal_options(self) -> dict:
        """List visible ideas/actions that can be linked to goals.
        """
        return self._json('GET', 'timeline/ideas/goal-options')

    def get_map(self, identity: str) -> dict:
        """Read a mind map and current version.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
        """
        return self._json('GET', f'timeline/ideas/maps/{self._segment(identity)}')

    def get_map_graph(self, identity: str) -> dict:
        """Read the visible graph projection for map members.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
        """
        return self._json('GET', f'timeline/ideas/maps/{self._segment(identity)}/graph')

    def list_map_attach_options(self, identity: str, query: str = '', offset: int = 0) -> dict:
        """Search attachable objects; returns 50 per page.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            query: Search text; empty means no text filter.
            offset: Nonnegative pagination offset.
        """
        return self._json('GET', f'timeline/ideas/maps/{self._segment(identity)}/attach-options', params=dict(query=query, offset=offset))

    def get_rendered_markdown(self, body: str) -> dict:
        """Render up to 60000 characters of Markdown using the frontend renderer. Read-only.

        Args:
            body: Body.
        """
        return self._json('POST', 'timeline/ideas/render', payload=dict(body=body))

    def get_idea(self, identity: str) -> dict:
        """Read an idea, version and rendered content.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
        """
        return self._json('GET', f'timeline/ideas/objects/{self._segment(identity)}')

    def create_idea(self, request_id: str, title: str, fields: dict | None = None) -> dict:
        """Create an idea; reuse the request UUID for stable identity. Destructive: writes remote state.

        Args:
            request_id: Caller-generated UUID; reuse with identical content when retrying.
            title: Title.
            fields: Optional description, body, checklists, status, source, expected_outcome, matrix, matrix_confidence, matrix_reason, source_date, workspace_ids, board_ids (optional list of active board IDs).
        """
        return self._json('POST', 'timeline/ideas/objects', payload={**(fields or {}), 'request_id': request_id, 'title': title})

    def update_idea(self, identity: str, version: int, changes: dict) -> dict:
        """Edit/dismiss/restore an idea using the latest version. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            version: Latest object version; stale writes return 409. Read before retrying.
            changes: Changed title, description, body, checklists, status, source, expected_outcome, matrix, matrix_confidence, matrix_reason, source_date, workspace_ids, board_ids (optional list of active board IDs).
        """
        return self._json('PATCH', f'timeline/ideas/objects/{self._segment(identity)}', payload={**changes, 'version': version})

    def create_topic(self, label: str) -> dict:
        """Create a named graph topic and initial entity profile; URLs are not topic names. Destructive: writes remote state.

        Args:
            label: Label.
        """
        return self._json('POST', 'timeline/ideas/topics', payload=dict(label=label))

    def create_link(self, source: str, target: str, relation: str = 'related-to') -> dict:
        """Create a durable relation between visible graph nodes. Destructive: writes remote state.

        Args:
            source: Source.
            target: Target.
            relation: Relation.
        """
        return self._json('POST', 'timeline/ideas/links', payload=dict(source=source, target=target, relation=relation))

    def delete_link(self, source: str, target: str, relation: str = 'related-to') -> dict:
        """Delete a durable relation between visible graph nodes. Destructive: writes remote state.

        Args:
            source: Source.
            target: Target.
            relation: Relation.
        """
        return self._json('DELETE', 'timeline/ideas/links', payload=dict(source=source, target=target, relation=relation))

    def create_map(self, request_id: str, name: str, fields: dict | None = None) -> dict:
        """Create a versioned mind map; UUID determines its stable identity. Destructive: writes remote state.

        Args:
            request_id: Caller-generated UUID; reuse with identical content when retrying.
            name: Map name, 1–100 characters.
            fields: Optional members, positions, node_sizes, edge_widths, prompt, purpose, root, goal_id, drafts, edges, board_date, active (boolean, default true) and color.
        """
        return self._json('POST', 'timeline/ideas/maps', payload={**(fields or {}), 'request_id': request_id, 'name': name})

    def update_map(self, identity: str, version: int, changes: dict) -> dict:
        """Update map membership/content/layout with an optimistic version check. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            version: Latest object version; stale writes return 409. Read before retrying.
            changes: Map fields to change: name, members, positions, node_sizes, edge_widths, prompt, purpose, root, goal_id, drafts, edges, board_date, active, color.
        """
        return self._json('PATCH', f'timeline/ideas/maps/{self._segment(identity)}', payload={**changes, 'version': version})

    def delete_map(self, identity: str, version: int) -> dict:
        """Delete a map using its latest version; shared objects remain independently owned. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            version: Latest object version; stale writes return 409. Read before retrying.
        """
        return self._json('DELETE', f'timeline/ideas/maps/{self._segment(identity)}', payload=dict(version=version))

    def create_map_promotion(self, identity: str, draft_id: str, version: int) -> dict:
        """Promote a map draft into a durable idea. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            draft_id: Draft id.
            version: Latest object version; stale writes return 409. Read before retrying.
        """
        return self._json('POST', f'timeline/ideas/maps/{self._segment(identity)}/promote', payload=dict(draft_id=draft_id, version=version))

    def get_goal(self, identity: str) -> dict:
        """Read a goal with its current version.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
        """
        return self._json('GET', f'timeline/ideas/goals/{self._segment(identity)}')

    def create_map_link_promotion(
        self,
        identity: str,
        source: str,
        target: str,
        version: int,
        relation: str = 'related-to',
    ) -> dict:
        """Promote a map connection to a durable graph relation. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            source: Source.
            target: Target.
            version: Latest object version; stale writes return 409. Read before retrying.
            relation: Relation.
        """
        return self._json('POST', f'timeline/ideas/maps/{self._segment(identity)}/promote-link', payload=dict(edge=dict(source=source, target=target, relation=relation), version=version))

    def update_map_connection(self, identity: str, changes: dict) -> dict:
        """Edit a board connection using its current board/edge revision. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            changes: Command: operation (create/update/remove/width), scope (local/shared), edge {source,target,relation,direction}, replacement (optional), version, revision for shared edges, width for width operations.
        """
        return self._json('POST', f'timeline/ideas/maps/{self._segment(identity)}/connections', payload=changes)

    def create_goal(self, request_id: str, title: str, fields: dict | None = None) -> dict:
        """Create a durable goal with validated idea/action links. Destructive: writes remote state.

        Args:
            request_id: Caller-generated UUID; reuse with identical content when retrying.
            title: Title.
            fields: Optional body, success_criteria, status, target_date, progress_notes, milestones, linked_objects and color.
        """
        return self._json('POST', 'timeline/ideas/goals', payload={**(fields or {}), 'request_id': request_id, 'title': title})

    def update_goal(self, identity: str, version: int, changes: dict) -> dict:
        """Update a goal with optimistic concurrency and validated milestone links. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            version: Latest object version; stale writes return 409. Read before retrying.
            changes: Changed title, body, success_criteria, status, target_date, progress_notes, milestones, linked_objects or color.
        """
        return self._json('PATCH', f'timeline/ideas/goals/{self._segment(identity)}', payload={**changes, 'version': version})

    def get_idea_conversion(self, identity: str, checklist_id: str = '', item_id: str = '') -> dict:
        """Preview conversion of an idea or checklist item into an action.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            checklist_id: Checklist id.
            item_id: Item id.
        """
        return self._json('GET', f'timeline/ideas/objects/{self._segment(identity)}/conversion', params=dict(checklist_id=checklist_id, item_id=item_id))

    def create_idea_conversion(
        self,
        identity: str,
        request_id: str,
        idea_version: int,
        item: dict,
        attachments: list[str] | None = None,
        checklist_id: str = '',
        item_id: str = '',
    ) -> dict:
        """Convert an idea to an action, clone selected attachments, and mark it adopted. Agent execution remains disabled. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            request_id: Caller-generated UUID; reuse with identical content when retrying.
            idea_version: Idea version.
            item: Action draft returned by get_hfl_corpus_idea_conversion, with any reviewed field edits.
            attachments: Attachment IDs to clone, not local file paths.
            checklist_id: Checklist id.
            item_id: Item id.
        """
        return self._json('POST', f'timeline/ideas/objects/{self._segment(identity)}/convert', payload=dict(request_id=request_id, idea_version=idea_version, item=item, attachments=attachments or [], checklist_id=checklist_id, item_id=item_id))

    def list_idea_attachments(self, identity: str) -> dict:
        """List an idea’s supporting files.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
        """
        return self._json('GET', f'timeline/ideas/objects/{self._segment(identity)}/attachments')

    def download_idea_attachment(self, identity: str, attachment_id: str, destination: str) -> dict:
        """Download a supporting file to a local path; replaces an existing destination. Destructive: writes a local file.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            attachment_id: Attachment ID from the list/upload response.
            destination: Local destination file path on the MCP host.
        """
        return self._download(f'timeline/ideas/objects/{self._segment(identity)}/attachments/{self._segment(attachment_id)}', destination)

    def upload_idea_attachments(self, identity: str, file_paths: list[str]) -> dict:
        """Attach supporting files to an idea; at most 50 files of 500 MB each. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            file_paths: Local readable file paths on the MCP host.
        """
        return self._upload_files(f'timeline/ideas/objects/{self._segment(identity)}/attachments', file_paths)

    def delete_idea_attachment(self, identity: str, attachment_id: str) -> dict:
        """Detach a supporting file from an idea. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            attachment_id: Attachment ID from the list/upload response.
        """
        return self._json('DELETE', f'timeline/ideas/objects/{self._segment(identity)}/attachments/{self._segment(attachment_id)}')

    def create_map_proposal(
        self,
        identity: str,
        request_id: str,
        item: dict,
        parents: list[str] | None = None,
    ) -> dict:
        """Accept a proposed thought into a map with at most five existing parents. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            request_id: Caller-generated UUID; reuse with identical content when retrying.
            item: Proposed title, description and/or body only.
            parents: Parents.
        """
        return self._json('POST', f'timeline/ideas/maps/{self._segment(identity)}/accept-proposal', payload=dict(request_id=request_id, item=item, parents=parents or []))
