"""Airtable Tables / Fields service — base schema introspection and mutation."""
from typing import List, Optional, Dict, Any

from apps.airtable.references.web.base_api_service import BaseApiServiceAirtable
from apps.airtable.references.dto.tables import DtoAirtableTable, DtoAirtableField, DtoAirtableView


def _map_field(d: dict) -> DtoAirtableField:
    return DtoAirtableField(
        id=d.get("id"),
        name=d.get("name"),
        type=d.get("type"),
        description=d.get("description"),
        options=d.get("options"),
    )


def _map_view(d: dict) -> DtoAirtableView:
    return DtoAirtableView(id=d.get("id"), name=d.get("name"), type=d.get("type"))


def _map_table(d: dict) -> DtoAirtableTable:
    return DtoAirtableTable(
        id=d.get("id"),
        name=d.get("name"),
        description=d.get("description"),
        primaryFieldId=d.get("primaryFieldId"),
        fields=[_map_field(f) for f in d.get("fields") or []],
        views=[_map_view(v) for v in d.get("views") or []],
    )


class ApiServiceAirtableTables(BaseApiServiceAirtable):
    """Base schema endpoints — tables, fields, views."""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    def list_tables(self, base_id: str) -> List[DtoAirtableTable]:
        """List all tables (with their fields and views) in a base."""
        data = self._get(f"/meta/bases/{base_id}/tables")
        return [_map_table(t) for t in (data.get("tables") or [])]

    def create_table(
        self,
        base_id: str,
        name: str,
        fields: List[Dict[str, Any]],
        description: Optional[str] = None,
    ) -> DtoAirtableTable:
        """Create a new table in a base.

        `fields` must be a list of field definitions, each with at minimum
        `name` and `type`. The first field in the list becomes the primary field.
        """
        body: dict = {"name": name, "fields": fields}
        if description:
            body["description"] = description
        return _map_table(self._post(f"/meta/bases/{base_id}/tables", body))

    def update_table(
        self,
        base_id: str,
        table_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> DtoAirtableTable:
        """Update a table's name or description."""
        body: dict = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        return _map_table(self._patch(f"/meta/bases/{base_id}/tables/{table_id}", body))

    def create_field(
        self,
        base_id: str,
        table_id: str,
        name: str,
        type: str,
        options: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
    ) -> DtoAirtableField:
        """Add a new field to an existing table."""
        body: dict = {"name": name, "type": type}
        if options:
            body["options"] = options
        if description:
            body["description"] = description
        return _map_field(self._post(f"/meta/bases/{base_id}/tables/{table_id}/fields", body))

    def update_field(
        self,
        base_id: str,
        table_id: str,
        field_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> DtoAirtableField:
        """Update an existing field's name or description."""
        body: dict = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        return _map_field(
            self._patch(f"/meta/bases/{base_id}/tables/{table_id}/fields/{field_id}", body)
        )
