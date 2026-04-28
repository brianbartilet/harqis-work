from dataclasses import dataclass
from typing import Optional, List, Any


@dataclass
class DtoPerplexityMessage:
    role: Optional[str] = None
    content: Optional[str] = None


@dataclass
class DtoPerplexityChoice:
    index: Optional[int] = None
    finish_reason: Optional[str] = None
    message: Optional[DtoPerplexityMessage] = None


@dataclass
class DtoPerplexityUsage:
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    citation_tokens: Optional[int] = None
    num_search_queries: Optional[int] = None


@dataclass
class DtoPerplexityChatResponse:
    id: Optional[str] = None
    object: Optional[str] = None
    created: Optional[int] = None
    model: Optional[str] = None
    choices: Optional[List[DtoPerplexityChoice]] = None
    usage: Optional[DtoPerplexityUsage] = None
    citations: Optional[List[str]] = None
    output_text: Optional[str] = None
