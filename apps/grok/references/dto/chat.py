from dataclasses import dataclass, field
from typing import Optional, List, Any


@dataclass
class DtoGrokUsage:
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    prompt_tokens_details: Optional[dict] = None
    completion_tokens_details: Optional[dict] = None


@dataclass
class DtoGrokMessage:
    role: Optional[str] = None
    content: Optional[str] = None
    tool_calls: Optional[List[Any]] = None


@dataclass
class DtoGrokChoice:
    index: Optional[int] = None
    message: Optional[DtoGrokMessage] = None
    finish_reason: Optional[str] = None


@dataclass
class DtoGrokResponse:
    id: Optional[str] = None
    object: Optional[str] = None
    created: Optional[int] = None
    model: Optional[str] = None
    choices: Optional[List[DtoGrokChoice]] = field(default_factory=list)
    usage: Optional[DtoGrokUsage] = None
    output_text: Optional[str] = None


@dataclass
class DtoGrokModel:
    id: Optional[str] = None
    object: Optional[str] = None
    created: Optional[int] = None
    owned_by: Optional[str] = None


@dataclass
class DtoGrokEmbedding:
    object: Optional[str] = None
    embedding: Optional[List[float]] = None
    index: Optional[int] = None


@dataclass
class DtoGrokEmbeddingResponse:
    object: Optional[str] = None
    data: Optional[List[DtoGrokEmbedding]] = field(default_factory=list)
    model: Optional[str] = None
    usage: Optional[DtoGrokUsage] = None
