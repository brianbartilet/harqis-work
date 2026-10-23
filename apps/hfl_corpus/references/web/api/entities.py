"""Typed canonical entities API operations."""
from __future__ import annotations

from apps.hfl_corpus.references.web.api.extended import ApiServiceHflCorpusExtended


class ApiServiceHflCorpusEntities(ApiServiceHflCorpusExtended):

    def get_entity_connections(self, identity: str) -> dict:
        """Read entity connections and their edit versions."""
        return self._json('GET', f'entities/connections/{self._segment(identity)}')

    def update_entity_connections(self, identity: str, changes: list[dict], versions: dict) -> dict:
        """Apply reviewed connection changes with the versions from the read endpoint."""
        return self._json('POST', f'entities/connections/{self._segment(identity)}', payload=dict(changes=changes, versions=versions))

    def list_entity_connection_activities(self, query: str = '') -> dict:
        """Find bounded activity choices for entity connections."""
        return self._json('GET', 'entities/connection-activities', params={'q': query})

    def update_entity_owner_binding(self, identity: str) -> dict:
        """Bind the corpus owner to a reviewed existing person identity."""
        return self._json('POST', 'entities/owner-binding', payload=dict(identity=identity))

    def update_entity_resolution_undo(self, entry_id: str, mention_id: str) -> dict:
        """Undo one mention assignment and record its exclusion."""
        return self._json('POST', f'entities/resolutions/{self._segment(entry_id)}/{self._segment(mention_id)}/undo')

    def get_entity_merge_members(self, identity: str) -> dict:
        """Read merged members available for a detach preview."""
        return self._json('GET', f'entities/merges/{self._segment(identity)}/members')

    def analyze_entity_detach(self, identity: str, member_id: str) -> dict:
        """Preview detaching one member and obtain its review token; read-only."""
        return self._json('POST', f'entities/merges/{self._segment(identity)}/detach-preview', payload=dict(member_id=member_id))

    def update_entity_detach(self, identity: str, member_id: str, request_id: str, preview_token: str) -> dict:
        """Commit a reviewed detach; reuse the same UUID and payload on retry."""
        return self._json('POST', f'entities/merges/{self._segment(identity)}/detach', payload=dict(member_id=member_id, request_id=request_id, preview_token=preview_token))

    def update_entity_types_batch(self, entity_ids: list[str], kind: str, source_kinds: dict) -> dict:
        """Reclassify selected entities after checking their observed source kinds."""
        return self._json('POST', 'entities/types/batch', payload=dict(entity_ids=entity_ids, kind=kind, source_kinds=source_kinds))

    def update_entity_type_properties(self, identity: str, name: str, color: str, description: str) -> dict:
        """Edit a type's display and extraction properties without starting backfill."""
        return self._json('POST', f'entities/types/{self._segment(identity)}/update', payload=dict(name=name, color=color, description=description))

    def get_entity_context(self, identity: str) -> dict:
        """Read a current entity's soul, identity rules, relationships and bounded activity."""
        return self._json('GET', f'entities/context/{self._segment(identity)}')

    def update_entity_soul(self, identity: str, soul: dict) -> dict:
        """Replace soul fields using the version from get_entity_context. Writes remote state."""
        return self._json('POST', f'entities/soul/{self._segment(identity)}', payload=soul)

    def get_entity_soul_editor(self, identity: str) -> dict:
        """Read profile, identity, connections and the revision for a coordinated edit."""
        return self._json('GET', f'entities/soul-editor/{self._segment(identity)}')

    def update_entity_soul_editor(self, identity: str, update: dict) -> dict:
        """Atomically replace owner-authored fields; remote write requires editor revision."""
        return self._json('POST', f'entities/soul-editor/{self._segment(identity)}', payload=update)

    def list_entities(
        self,
        query: str = '',
        kind: str = '',
        offset: int = 0,
        limit: int = 100,
        source: str = '',
        since: str = '',
        until: str = '',
        context: str = '',
        graph_query: str = '',
        sources: list[str] | None = None,
    ) -> dict:
        """Search the entity directory with explicit pagination (limit 1–10000).

        Args:
            query: Search text; empty means no text filter.
            kind: Kind.
            offset: Nonnegative pagination offset.
            limit: Maximum results; subject to server limits.
            source: Source.
            since: Lower date filter, YYYY-MM-DD or empty.
            until: Upper date filter, YYYY-MM-DD or empty.
            context: Context.
            graph_query: Graph query.
            sources: Repeated source filters; None omits the filter.
        """
        if not 1 <= limit <= 10000 or offset < 0:
            raise ValueError('Use limit 1–10000 and a nonnegative offset.')
        return self._json('GET', 'entities', params=dict(q=query, kind=kind, offset=offset, limit=limit, source=source, since=since, until=until, context=context, graph_query=graph_query, sources=sources))

    def get_entity_graph(
        self,
        query: str = '',
        limit: int = 100,
        source: str = '',
        since: str = '',
        until: str = '',
        shared: bool = False,
        sources: list[str] | None = None,
        context: str = '',
    ) -> dict:
        """Read the entity graph; limit is 0–1000, with 0 requesting all nodes.

        Args:
            query: Search text; empty means no text filter.
            limit: Maximum results; subject to server limits.
            source: Source.
            since: Lower date filter, YYYY-MM-DD or empty.
            until: Upper date filter, YYYY-MM-DD or empty.
            shared: Shared.
            sources: Repeated source filters; None omits the filter.
            context: Context.
        """
        return self._json('GET', 'entities/graph', params=dict(query=query, limit=limit, source=source, since=since, until=until, shared=shared, sources=sources, context=context))

    def get_entity_entry(self, entry_id: str, locator: str = '') -> dict:
        """Read an entity-linked entry preview and its safe references.

        Args:
            entry_id: Stable HFL entry ID.
            locator: Locator.
        """
        return self._json('GET', f'entities/entry/{self._segment(entry_id)}', params=dict(locator=locator))

    def get_entity_status(self) -> dict:
        """Read entity enrichment state and legacy merge decisions.
        """
        return self._json('GET', 'entities/status')

    def update_entity_profile(
        self,
        identity: str,
        name: str,
        categories: list[str] | None = None,
        emails: list[str] | None = None,
        phones: list[str] | None = None,
        references: list[str] | None = None,
        notes: str = '',
    ) -> dict:
        """Replace entity profile fields; omitted lists are cleared. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            name: Name.
            categories: Categories.
            emails: Emails.
            phones: Phones.
            references: References.
            notes: Notes.
        """
        return self._json('POST', f'entities/profile/{self._segment(identity)}', payload=dict(name=name, categories=categories or [], emails=emails or [], phones=phones or [], references=references or [], notes=notes))

    def create_entity_backfill(self, include_new_types: bool = False) -> dict:
        """Request entity enrichment/backfill on the canonical host. Destructive: writes remote state.
        """
        return self._json('POST', 'entities/backfill', params={'include_new_types': include_new_types})

    def create_entity_legacy_merge(self, alias: str, canonical: str, reason: str) -> dict:
        """Legacy pair merge; prefer the preview-token bulk merge flow. Destructive: writes remote state.

        Args:
            alias: Alias.
            canonical: Canonical.
            reason: Evidence explaining the merge, 5–1000 characters.
        """
        return self._json('POST', 'entities/merge', payload=dict(alias=alias, canonical=canonical, reason=reason))

    def update_entity_legacy_undo(self, decision_id: int) -> dict:
        """Undo a legacy pair-merge decision. Destructive: writes remote state.

        Args:
            decision_id: Decision id.
        """
        return self._json('POST', f'entities/decisions/{self._segment(decision_id)}/undo')

    def create_entity_export(self) -> dict:
        """Write the canonical host’s configured Obsidian export; requires HARQIS_OBSIDIAN_VAULT. Destructive: writes remote state.
        """
        return self._json('POST', 'entities/export')

    def analyze_entity_selection(self, entity_ids: list[str], name: str, evidence: str = '') -> dict:
        """Preview a same-type entity merge and obtain a short-lived preview token. Read-only.

        Args:
            entity_ids: Entity ids.
            name: Name.
            evidence: Evidence.
        """
        return self._json('POST', 'entities/merge-preview', payload=dict(entity_ids=entity_ids, name=name, evidence=evidence))

    def create_entity_merge(
        self,
        entity_ids: list[str],
        name: str,
        request_id: str,
        preview_token: str,
        evidence: str = '',
        profile: dict | None = None,
    ) -> dict:
        """Commit a reviewed entity merge; reuse the UUID and identical payload on retry. Destructive: writes remote state.

        Args:
            entity_ids: Entity ids.
            name: Name.
            request_id: Caller-generated UUID; reuse with identical content when retrying.
            preview_token: Token returned by analyze_hfl_corpus_entity_selection; expires after 15 minutes.
            evidence: Evidence.
            profile: Optional overrides: categories, emails, phones, references, notes; omitted keys are preserved.
        """
        return self._json('POST', 'entities/merges', payload=dict(entity_ids=entity_ids, name=name, request_id=request_id, preview_token=preview_token, evidence=evidence, **({'profile': profile} if profile is not None else {})))

    def update_entity_unmerge(self, identity: str, request_id: str, evidence: str = '') -> dict:
        """Reverse a bulk merge, preserving audit history; UUID is required for idempotency. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
            request_id: Caller-generated UUID; reuse with identical content when retrying.
            evidence: Evidence.
        """
        return self._json('POST', f'entities/merges/{self._segment(identity)}/unmerge', payload=dict(request_id=request_id, evidence=evidence))

    def get_entity_operation(self, request_id: str) -> dict:
        """Read a committed merge/unmerge result and audit delivery state.

        Args:
            request_id: Caller-generated UUID; reuse with identical content when retrying.
        """
        return self._json('GET', f'entities/operations/{self._segment(request_id)}')

    def get_entity_audit(self, identity: str) -> dict:
        """Read immutable entity merge/unmerge audit events.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
        """
        return self._json('GET', f'entities/audit/{self._segment(identity)}')

    def get_entity_matching(self, all: bool = False) -> dict:
        """Read matching scan status and candidate suggestions.
        """
        return self._json('GET', 'entities/matching', params={'all': all})

    def create_entity_matching_scan(self) -> dict:
        """Request a matching scan; this may schedule background work. Destructive: writes remote state.
        """
        return self._json('POST', 'entities/matching/scan')

    def update_entity_matching_dismiss(self, identity: str) -> dict:
        """Dismiss a matching suggestion. Destructive: writes remote state.

        Args:
            identity: Resource ID returned by the corresponding list/get operation.
        """
        return self._json('POST', f'entities/matching/suggestions/{self._segment(identity)}/dismiss')

    def create_entity_type(self, name: str, color: str, description: str) -> dict:
        """Create an entity type used by future extraction; historical backfill is explicit."""
        return self._json('POST', 'entities/types', payload=dict(name=name, color=color, description=description))

    def create_entity(self, name: str, kind: str, categories: list[str] | None = None,
                      emails: list[str] | None = None, phones: list[str] | None = None,
                      references: list[str] | None = None, notes: str = '', confirm_distinct: bool = False) -> dict:
        """Create a manual entity or return possible-existing suggestions.

        Set confirm_distinct only after choosing a genuinely distinct identity.
        Destructive: writes remote state.
        """
        return self._json('POST', 'entities/create', payload=dict(name=name, kind=kind,
            categories=categories or [], emails=emails or [], phones=phones or [], references=references or [], notes=notes, confirm_distinct=confirm_distinct))

    def update_entity_type(self, identity: str, kind: str) -> dict:
        """Change an existing entity to a configured type without discarding its profile."""
        return self._json('POST', f'entities/type/{self._segment(identity)}', payload={'kind': kind})

    def create_entity_merge_batch(self, groups: list[dict]) -> dict:
        """Submit up to 100 reviewed, disjoint groups; each needs entity_ids, name,
        request_id and preview_token from analyze_hfl_corpus_entity_selection.
        Optional evidence and profile edits follow create_entity_merge. Reuse identical
        group payloads and request IDs on retry; results report each success or failure.
        """
        return self._json('POST', 'entities/merges/batch', payload={'groups': groups})

    def create_entity_consolidation(self, compact: bool = False) -> dict:
        """Begin or resume an entity consolidation run. Destructive: writes remote state.

        Args:
            compact: Deduplicate entity evidence in the response.
        """
        return self._json('POST', 'entities/consolidation/begin', params={'compact': compact})

    def get_entity_consolidation(self, run_id: str, compact: bool = False, limit: int = 20) -> dict:
        """Read a consolidation run and its candidate decisions.

        Args:
            run_id: Run ID returned by create_hfl_corpus_entity_consolidation.
            compact: Deduplicate entity evidence in the response.
            limit: Maximum returned pairs, 1-20.
        """
        return self._json('GET', f'entities/consolidation/{self._segment(run_id)}', params={'compact': compact, 'limit': limit})

    def update_entity_consolidation_decision(self, run_id: str, pair_id: str, decision: dict) -> dict:
        """Record a decision and apply an eligible merge. Destructive: writes remote state.

        Args:
            run_id: Consolidation run ID.
            pair_id: Candidate pair ID from the run.
            decision: decision (merge/review/separate), reason, and optional contradictions, facts, aliases and partial_aliases. Facts contain left_quote, right_quote and explanation.
        """
        return self._json('POST', f'entities/consolidation/{self._segment(run_id)}/decisions/{self._segment(pair_id)}', payload=decision)

    def update_entity_consolidation_decisions(self, run_id: str, decisions: dict, claim_token: str | None = None) -> dict:
        """Submit up to 20 pair decisions; results report each success or error. Destructive: writes remote state.

        Args:
            run_id: Consolidation run ID.
            decisions: Pair IDs mapped to decision objects, as in update_hfl_corpus_entity_consolidation_decision.
            claim_token: Active review lease token, if claimed.
        """
        payload = {'decisions': decisions}
        if claim_token is not None:
            payload['claim_token'] = claim_token
        return self._json('POST', f'entities/consolidation/{self._segment(run_id)}/decisions', payload=payload)

    def create_entity_consolidation_claim(self, run_id: str, worker_id: str, max_pairs: int = 8,
                                          max_bytes: int = 100000, lease_seconds: int = 900) -> dict:
        """Claim a disjoint anchor packet. Destructive: writes remote state."""
        return self._json('POST', f'entities/consolidation/{self._segment(run_id)}/claims',
            payload=dict(worker_id=worker_id, max_pairs=max_pairs, max_bytes=max_bytes, lease_seconds=lease_seconds))

    def update_entity_consolidation_claim(self, run_id: str, token: str, action: str, lease_seconds: int = 900) -> dict:
        """Renew or release a review lease. Destructive: writes remote state."""
        return self._json('POST', f'entities/consolidation/{self._segment(run_id)}/claims/{self._segment(token)}',
                          payload=dict(action=action, lease_seconds=lease_seconds))

    def update_entity_consolidation_checkpoint(self, run_id: str) -> dict:
        """Checkpoint partial progress and discover changed inputs. Destructive: writes remote state."""
        return self._json('POST', f'entities/consolidation/{self._segment(run_id)}/checkpoint')

    def update_entity_consolidation_evidence(self, run_id: str, entity_id: str, entry_ids: list[str],
                                            claim_token: str | None = None) -> dict:
        """Cache bounded original-entry context across pending pairs. Destructive: writes remote state."""
        return self._json('POST', f'entities/consolidation/{self._segment(run_id)}/evidence',
                          payload=dict(entity_id=entity_id, entry_ids=entry_ids, claim_token=claim_token))

    def create_entity_consolidation_group(self, run_id: str, anchor_id: str, decisions: dict,
                                         contradictions: list[str], claim_token: str | None = None) -> dict:
        """Commit independently corroborated anchor pairs atomically. Destructive: writes remote state."""
        return self._json('POST', f'entities/consolidation/{self._segment(run_id)}/groups',
            payload=dict(anchor_id=anchor_id, decisions=decisions, contradictions=contradictions, claim_token=claim_token))

    def update_entity_consolidation_finish(self, run_id: str) -> dict:
        """Finish a decided run and dispatch its reports. Destructive: writes remote state.

        Args:
            run_id: Consolidation run ID; unfinished decisions prevent completion.
        """
        return self._json('POST', f'entities/consolidation/{self._segment(run_id)}/finish')

    def search_entity_duplicates(self, name: str, kind: str) -> dict:
        """Suggest existing identities before manual creation.

        Args:
            name: Proposed display name.
            kind: Registered entity kind.
        """
        return self._json('POST', 'entities/possible-existing', payload=dict(name=name, kind=kind))

    def get_entity_resolution_health(self) -> dict:
        """Read resolver throughput, pending age, failures and outcomes.
        """
        return self._json('GET', 'entities/resolution')

    def update_entity_resolution_retry(self, entry_id: str) -> dict:
        """Requeue one investigated failed resolver job. Destructive: writes remote state.

        Args:
            entry_id: Failed source entry ID.
        """
        return self._json('POST', f'entities/resolution/{self._segment(entry_id)}/retry')

    def update_entity_integrity(self, identity: str, review: dict) -> dict:
        """Set or clear an audited identity-review flag. Destructive: writes remote state.

        Args:
            identity: Active established identity ID.
            review: Object with required boolean, evidence-backed reason, and optional originating operation_ids.
        """
        return self._json('POST', f'entities/integrity/{self._segment(identity)}', payload=review)

    def update_entity_separation_reverse(self, left_id: str, right_id: str, reason: str) -> dict:
        """Reverse a consolidation separation while preserving unmerge vetoes. Destructive: writes remote state.

        Args:
            left_id: First identity ID.
            right_id: Second identity ID.
            reason: Evidence supporting reversal.
        """
        return self._json('POST', 'entities/separations/reverse', payload=dict(left_id=left_id, right_id=right_id, reason=reason))

    def create_entity_consolidation_execution(self, run_id: str, execution_id: str, max_pairs: int = 40, seconds: int = 900) -> dict:
        """Start or recover a bounded consolidation execution. Destructive: writes remote state.

        Args:
            run_id: Durable consolidation run ID.
            execution_id: Stable caller ID reused on retry.
            max_pairs: Fixed selection size, 1-200 comparisons.
            seconds: Execution budget, 30-3600 seconds.
        """
        return self._json('POST', f'entities/consolidation/{self._segment(run_id)}/executions', payload=dict(execution_id=execution_id, max_pairs=max_pairs, seconds=seconds))

    def update_entity_consolidation_execution_close(self, run_id: str, execution_id: str, reason: str, errors: list[str] | None = None) -> dict:
        """Close a bounded execution and dispatch its canonical report. Destructive: writes remote state.

        Args:
            run_id: Durable consolidation run ID.
            execution_id: Execution ID returned at start.
            reason: budget, exhausted, provider-failure, or integrity-concern.
            errors: Optional sanitized operational errors; reuse identical values on replay.
        """
        return self._json('POST', f'entities/consolidation/{self._segment(run_id)}/executions/{self._segment(execution_id)}/close', payload=dict(reason=reason, errors=errors or []))
