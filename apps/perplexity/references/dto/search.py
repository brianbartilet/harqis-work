from dataclasses import dataclass
from typing import Optional, List


@dataclass
class DtoPerplexitySearchResult:
    title: Optional[str] = None
    url: Optional[str] = None
    snippet: Optional[str] = None
    date: Optional[str] = None
    last_updated: Optional[str] = None


@dataclass
class DtoPerplexitySearchResponse:
    results: Optional[List[DtoPerplexitySearchResult]] = None
    query: Optional[str] = None
