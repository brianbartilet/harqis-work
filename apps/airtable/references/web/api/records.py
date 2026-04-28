"""Airtable Records service — CRUD on rows in a base/table.

Pagination: response includes an `offset` token; pass it back as the
`offset` query parameter on the next call to fetch the next page.
Max 100 records per list page; max 10 records per write call.

Docs: https://airtable.com/developers/web/api/list-records
"""
from typing import List, Optional, Dict, Any
from urllib.parse import quote

from apps.airtable.references.web.base_api_service import BaseApiServiceAirtable
from apps.airtable.references.dto.records import DtoAirtableRecord, DtoAirtableRecordsPage


def _map_record(d: dict) -> DtoAirtableRecord:
    return DtoAirtableRecord(
        id=d.get("id"),
        createdTime=d.get("createdTime"),
        fields=d.get("fields") or {},
    )


def _table_path(base_id: str, table: str) -> str:
    # `table` may be a table id (tbl...) or a table name — encode the latter for URL safety.
    return f"/{base_id}/{quote(table, safe='')}"


class ApiServiceAirtableRecords(BaseApiServiceAirtable):
    """Records CRUD for a single base/table."""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    def list_records(
        self,
        base_id: str,
        table: str,
        view: Optional[str] = None,
        filter_by_formula: Optional[str] = None,
        max_records: Optional[int] = None,
        page_size: Optional[int] = None,
        sort: Optional[List[Dict[str, str]]] = None,
        fields: Optional[List[str]] = None,
        offset: Optional[str] = None,
    ) -> DtoAirtableRecordsPage:
        """List records from a table. Returns one page (use `offset` to paginate).

        Args:
            base_id:           Base id (`app...`).
            table:             Table id (`tbl...`) or human-readable name.
            view:              Restrict results to records visible in this view.
            filter_by_formula: Airtable formula expression, e.g. `"{Status}='Done'"`.
            max_records:       Maximum total records to return.
            page_size:         Records per page (default 100, max 100).
            sort:              List of `{field, direction}` dicts, e.g.
                               `[{"field": "Name", "direction": "asc"}]`.
            fields:            Only return these field names.
            offset:            Pagination token from a previous response.
        """
        params: dict = {}
        if view:
            params["view"] = view
        if filter_by_formula:
            params["filterByFormula"] = filter_by_formula
        if max_records:
            params["maxRecords"] = max_records
        if page_size:
            params["pageSize"] = page_size
        if offset:
            params["offset"] = offset
        if fields:
            for i, f in enumerate(fields):
                params[f"fields[{i}]"] = f
        if sort:
            for i, s in enumerate(sort):
                params[f"sort[{i}][field]"] = s.get("field", "")
                if s.get("direction"):
                    params[f"sort[{i}][direction]"] = s["direction"]

        data = self._get(_table_path(base_id, table), params=params)
        return DtoAirtableRecordsPage(
            records=[_map_record(r) for r in data.get("records") or []],
            offset=data.get("offset"),
        )

    def list_all_records(
        self,
        base_id: str,
        table: str,
        view: Optional[str] = None,
        filter_by_formula: Optional[str] = None,
        max_records: Optional[int] = None,
        sort: Optional[List[Dict[str, str]]] = None,
        fields: Optional[List[str]] = None,
    ) -> List[DtoAirtableRecord]:
        """Auto-paginate through all matching records."""
        all_records: List[DtoAirtableRecord] = []
        offset: Optional[str] = None
        while True:
            page = self.list_records(
                base_id=base_id, table=table, view=view,
                filter_by_formula=filter_by_formula, max_records=max_records,
                sort=sort, fields=fields, offset=offset,
            )
            all_records.extend(page.records or [])
            offset = page.offset
            if not offset:
                break
            if max_records and len(all_records) >= max_records:
                return all_records[:max_records]
        return all_records

    def get_record(self, base_id: str, table: str, record_id: str) -> DtoAirtableRecord:
        """Fetch a single record by id."""
        data = self._get(f"{_table_path(base_id, table)}/{record_id}")
        return _map_record(data)

    def create_records(
        self,
        base_id: str,
        table: str,
        records: List[Dict[str, Any]],
        typecast: bool = False,
    ) -> List[DtoAirtableRecord]:
        """Create up to 10 records. Each item in `records` is the `fields` dict.

        Args:
            base_id:  Base id.
            table:    Table id or name.
            records:  List of field-dicts, e.g. `[{"Name": "Alice", "Age": 30}, …]`.
            typecast: Allow Airtable to coerce string values to the field's type.
        """
        payload = {
            "records": [{"fields": r} for r in records],
            "typecast": typecast,
        }
        data = self._post(_table_path(base_id, table), payload)
        return [_map_record(r) for r in data.get("records") or []]

    def update_records(
        self,
        base_id: str,
        table: str,
        records: List[Dict[str, Any]],
        typecast: bool = False,
        replace: bool = False,
    ) -> List[DtoAirtableRecord]:
        """Update up to 10 records.

        Each item must be `{"id": "rec...", "fields": {...}}`.
        Default is partial update (PATCH); set `replace=True` for full replace (PUT).
        """
        payload = {"records": records, "typecast": typecast}
        path = _table_path(base_id, table)
        data = self._put(path, payload) if replace else self._patch(path, payload)
        return [_map_record(r) for r in data.get("records") or []]

    def upsert_records(
        self,
        base_id: str,
        table: str,
        records: List[Dict[str, Any]],
        merge_on: List[str],
        typecast: bool = False,
    ) -> dict:
        """Upsert up to 10 records, matching existing rows on `merge_on` fields.

        Args:
            records:  Each item should be `{"fields": {...}}` (no id).
            merge_on: List of field names whose values uniquely identify a row.
        """
        payload = {
            "records": records,
            "typecast": typecast,
            "performUpsert": {"fieldsToMergeOn": merge_on},
        }
        return self._patch(_table_path(base_id, table), payload)

    def delete_records(self, base_id: str, table: str, record_ids: List[str]) -> dict:
        """Delete up to 10 records by id."""
        params = [("records[]", rid) for rid in record_ids]
        # httpx accepts a list of (key, value) tuples for repeating params via dict-of-list:
        params_dict: dict = {}
        for k, v in params:
            params_dict.setdefault(k, []).append(v)
        return self._delete(_table_path(base_id, table), params=params_dict)
