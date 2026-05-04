from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class DtoAppSheetRow:
    """A single AppSheet row.

    AppSheet rows are arbitrary column-name → value maps; the schema is
    defined per-app in AppSheet itself, not in this client. Common system
    columns surface as top-level fields; everything else lands in `fields`.
    """

    fields: dict[str, Any] = field(default_factory=dict)
    row_id: Optional[str] = None
    row_number: Optional[int] = None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "DtoAppSheetRow":
        if not isinstance(payload, dict):
            return cls(fields={"_raw": payload})
        return cls(
            fields=dict(payload),
            row_id=payload.get("_RowNumber") and str(payload.get("_RowNumber")) or payload.get("Row ID"),
            row_number=payload.get("_RowNumber") if isinstance(payload.get("_RowNumber"), int) else None,
        )


@dataclass
class DtoAppSheetActionResult:
    """Result envelope for an AppSheet Add/Edit/Delete/Find call."""

    action: Optional[str] = None
    table: Optional[str] = None
    rows: list[DtoAppSheetRow] = field(default_factory=list)
    raw: Any = None
