from dataclasses import dataclass, field
from typing import Optional, List, Dict


@dataclass
class DtoAnthropicUsageEntry:
    """A single usage record for a model in a given time period."""
    model: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cache_creation_input_tokens: Optional[int] = None
    cache_read_input_tokens: Optional[int] = None
    # Populated by cost calculation, not the API
    estimated_cost_usd: Optional[float] = None


@dataclass
class DtoAnthropicUsageSummary:
    """Aggregated usage summary across all models."""
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_creation_tokens: int = 0
    total_cache_read_tokens: int = 0
    estimated_total_cost_usd: float = 0.0
    by_model: List[DtoAnthropicUsageEntry] = field(default_factory=list)
