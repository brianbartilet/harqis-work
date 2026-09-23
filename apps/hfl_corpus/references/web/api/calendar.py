"""Typed canonical calendar API operations."""
from __future__ import annotations

from apps.hfl_corpus.references.web.api.extended import ApiServiceHflCorpusExtended


class ApiServiceHflCorpusCalendar(ApiServiceHflCorpusExtended):

    def list_day_matches(
        self,
        activity_day: str,
        query: str = '',
        source: str = '',
        offset: int = 0,
        limit: int = 20,
        include_secrets: bool = False,
        secret_tags: str = '',
        scope: dict | None = None,
    ) -> dict:
        """Read matching entries across documents for one YYYY-MM-DD activity date; maximum 20 per page.

        Args:
            activity_day: Activity day.
            query: Search text; empty means no text filter.
            source: Source.
            offset: Nonnegative pagination offset.
            limit: Maximum results; subject to server limits.
            include_secrets: Include secrets.
            secret_tags: Secret tags.
            scope: Optional combined-view object with any/all filter clauses.
        """
        return self._json('GET', f'day-matches/{self._segment(activity_day)}', params=dict(q=query, source=source, offset=offset, limit=limit, include_secrets=include_secrets, secret_tags=secret_tags, scope=scope))
