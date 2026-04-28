from dataclasses import dataclass
from typing import Optional, List


@dataclass
class DtoPerplexityEmbedding:
    object: Optional[str] = None
    index: Optional[int] = None
    embedding: Optional[List[float]] = None


@dataclass
class DtoPerplexityEmbeddingUsage:
    prompt_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


@dataclass
class DtoPerplexityEmbeddingResponse:
    object: Optional[str] = None
    model: Optional[str] = None
    data: Optional[List[DtoPerplexityEmbedding]] = None
    usage: Optional[DtoPerplexityEmbeddingUsage] = None
