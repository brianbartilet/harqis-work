from dataclasses import dataclass, field
from typing import Optional, List, Any


@dataclass
class DtoGeminiModel:
    name: Optional[str] = None
    base_model_id: Optional[str] = None
    version: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    input_token_limit: Optional[int] = None
    output_token_limit: Optional[int] = None
    supported_generation_methods: Optional[List[str]] = field(default_factory=list)
    temperature: Optional[float] = None
    max_temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None


@dataclass
class DtoGeminiPart:
    text: Optional[str] = None
    inline_data: Optional[Any] = None


@dataclass
class DtoGeminiContent:
    parts: Optional[List[DtoGeminiPart]] = field(default_factory=list)
    role: Optional[str] = None


@dataclass
class DtoGeminiSafetyRating:
    category: Optional[str] = None
    probability: Optional[str] = None
    blocked: Optional[bool] = None


@dataclass
class DtoGeminiCandidate:
    content: Optional[DtoGeminiContent] = None
    finish_reason: Optional[str] = None
    index: Optional[int] = None
    safety_ratings: Optional[List[DtoGeminiSafetyRating]] = field(default_factory=list)
    token_count: Optional[int] = None


@dataclass
class DtoGeminiUsageMetadata:
    prompt_token_count: Optional[int] = None
    candidates_token_count: Optional[int] = None
    total_token_count: Optional[int] = None


@dataclass
class DtoGeminiGenerateContentResponse:
    candidates: Optional[List[DtoGeminiCandidate]] = field(default_factory=list)
    prompt_feedback: Optional[Any] = None
    usage_metadata: Optional[DtoGeminiUsageMetadata] = None


@dataclass
class DtoGeminiCountTokensResponse:
    total_tokens: Optional[int] = None
