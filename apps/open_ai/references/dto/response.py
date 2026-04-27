from dataclasses import dataclass, field
from typing import Optional, List, Any


@dataclass
class DtoOpenAiUsage:
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    input_tokens_details: Optional[dict] = None
    output_tokens_details: Optional[dict] = None


@dataclass
class DtoOpenAiOutputItem:
    """Represents one item in a Responses API output array.

    Fields are type-dependent:
      - type='message'              → role, content (list of content blocks)
      - type='code_interpreter_call' → code, outputs (list of DtoOpenAiCodeOutput)
      - type='web_search_call'       → content (search result blocks)
    """
    id: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    role: Optional[str] = None
    content: Optional[Any] = None
    code: Optional[str] = None
    outputs: Optional[Any] = None


@dataclass
class DtoOpenAiResponse:
    id: Optional[str] = None
    object: Optional[str] = None
    created_at: Optional[int] = None
    model: Optional[str] = None
    status: Optional[str] = None
    output: Optional[List[DtoOpenAiOutputItem]] = None
    output_text: Optional[str] = None
    usage: Optional[DtoOpenAiUsage] = None
    error: Optional[dict] = None
    metadata: Optional[dict] = None
    previous_response_id: Optional[str] = None


@dataclass
class DtoOpenAiCodeOutput:
    """One output item from a code_interpreter_call."""
    type: Optional[str] = None   # 'logs' | 'files'
    logs: Optional[str] = None
    files: Optional[List[dict]] = None


@dataclass
class DtoOpenAiCodeInterpreterCall:
    """Parsed code_interpreter_call output item from a Responses API response."""
    id: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    code: Optional[str] = None
    outputs: Optional[List[DtoOpenAiCodeOutput]] = field(default_factory=list)
