"""Perplexity Search API service.

POST /search — execute one or more web queries and retrieve relevant page contents.
Supports domain filters, language filters, and recency/date filters.

See: https://docs.perplexity.ai/docs/search
"""
from typing import Optional, List, Union

from apps.perplexity.references.web.base_api_service import BaseApiServicePerplexity
from apps.perplexity.references.dto.search import (
    DtoPerplexitySearchResponse,
    DtoPerplexitySearchResult,
)


class ApiServicePerplexitySearch(BaseApiServicePerplexity):
    """Perplexity Search — direct web search with domain/recency filtering."""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    def search(
        self,
        query: Union[str, List[str]],
        max_results: Optional[int] = None,
        search_domain_filter: Optional[List[str]] = None,
        search_recency_filter: Optional[str] = None,
        language: Optional[str] = None,
    ) -> DtoPerplexitySearchResponse:
        """Run one or more web search queries.

        Args:
            query:                 Either a single query string or a list of queries
                                   (the API accepts an array of strings).
            max_results:           Optional maximum number of results to return.
            search_domain_filter:  List of domains to restrict to (or '-domain' to exclude).
            search_recency_filter: Recency filter: 'month', 'week', 'day', or 'hour'.
            language:              ISO language code, e.g. 'en'.
        """
        queries = query if isinstance(query, list) else [query]
        body: dict = {"query": queries}
        if max_results is not None:
            body["max_results"] = max_results
        if search_domain_filter:
            body["search_domain_filter"] = search_domain_filter
        if search_recency_filter:
            body["search_recency_filter"] = search_recency_filter
        if language:
            body["language"] = language

        data = self._post("/search", body)
        return self._map(data, queries[0] if queries else None)

    def _map(self, data: dict, query: Optional[str]) -> DtoPerplexitySearchResponse:
        results = []
        for r in data.get("results") or []:
            results.append(DtoPerplexitySearchResult(
                title=r.get("title"),
                url=r.get("url"),
                snippet=r.get("snippet") or r.get("text"),
                date=r.get("date"),
                last_updated=r.get("last_updated"),
            ))
        return DtoPerplexitySearchResponse(results=results, query=query)
