"""Typed canonical entities API operations."""
from __future__ import annotations

from apps.hfl_corpus.references.web.api.extended import ApiServiceHflCorpusExtended


class ApiServiceHflCorpusEntities(ApiServiceHflCorpusExtended):

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
                      references: list[str] | None = None, notes: str = '') -> dict:
        """Create a manual entity of a configured type with optional profile details."""
        return self._json('POST', 'entities/create', payload=dict(name=name, kind=kind,
            categories=categories or [], emails=emails or [], phones=phones or [], references=references or [], notes=notes))

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
