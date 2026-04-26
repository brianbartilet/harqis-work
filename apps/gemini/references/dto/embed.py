from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class DtoGeminiEmbedding:
    values: Optional[List[float]] = field(default_factory=list)


@dataclass
class DtoGeminiEmbedContentResponse:
    embedding: Optional[DtoGeminiEmbedding] = None


@dataclass
class DtoGeminiBatchEmbedContentsResponse:
    embeddings: Optional[List[DtoGeminiEmbedding]] = field(default_factory=list)
