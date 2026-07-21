from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class DtoYouTubeAnalyticsReport:
    kind: Optional[str] = None
    column_headers: Optional[List[Dict[str, Any]]] = None
    rows: Optional[List[List[Any]]] = None
    raw: Optional[Dict[str, Any]] = None
