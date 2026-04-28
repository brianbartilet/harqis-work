"""Airtable MCP tools — bases, tables/fields, and record CRUD."""
import logging
from typing import Optional, List, Dict, Any

from mcp.server.fastmcp import FastMCP
from apps.airtable.config import CONFIG
from apps.airtable.references.web.api.bases import ApiServiceAirtableBases
from apps.airtable.references.web.api.tables import ApiServiceAirtableTables
from apps.airtable.references.web.api.records import ApiServiceAirtableRecords

logger = logging.getLogger("harqis-mcp.airtable")


def register_airtable_tools(mcp: FastMCP):

    @mcp.tool()
    def airtable_whoami() -> dict:
        """Return the authenticated Airtable user/PAT info (id, email, scopes)."""
        logger.info("Tool called: airtable_whoami")
        svc = ApiServiceAirtableBases(CONFIG)
        result = svc.whoami()
        logger.info("airtable_whoami id=%s", result.id)
        return result.__dict__

    @mcp.tool()
    def airtable_list_bases() -> list:
        """List all bases the authenticated PAT has access to."""
        logger.info("Tool called: airtable_list_bases")
        svc = ApiServiceAirtableBases(CONFIG)
        result = svc.list_bases()
        result = result if isinstance(result, list) else []
        logger.info("airtable_list_bases returned %d base(s)", len(result))
        return [b.__dict__ for b in result]

    @mcp.tool()
    def airtable_list_tables(base_id: str) -> list:
        """List all tables (with their fields and views) in a base.

        Args:
            base_id: Airtable base id, e.g. 'appXXXXXXXX'.
        """
        logger.info("Tool called: airtable_list_tables base_id=%s", base_id)
        svc = ApiServiceAirtableTables(CONFIG)
        result = svc.list_tables(base_id=base_id)
        result = result if isinstance(result, list) else []
        out = []
        for t in result:
            d = t.__dict__.copy()
            d["fields"] = [f.__dict__ for f in (t.fields or [])]
            d["views"] = [v.__dict__ for v in (t.views or [])]
            out.append(d)
        logger.info("airtable_list_tables returned %d table(s)", len(out))
        return out

    @mcp.tool()
    def airtable_list_records(
        base_id: str,
        table: str,
        view: Optional[str] = None,
        filter_by_formula: Optional[str] = None,
        max_records: Optional[int] = None,
        page_size: Optional[int] = None,
        sort: Optional[List[Dict[str, str]]] = None,
        fields: Optional[List[str]] = None,
        offset: Optional[str] = None,
    ) -> dict:
        """List records from a table — returns one page plus an `offset` for the next.

        Args:
            base_id:           Base id.
            table:             Table id or name.
            view:              Restrict to records visible in this view.
            filter_by_formula: Airtable formula, e.g. "{Status}='Done'".
            max_records:       Maximum records returned.
            page_size:         Records per page (default 100).
            sort:              List of {field, direction} dicts.
            fields:            Only return these field names.
            offset:            Pagination token from a previous call.
        """
        logger.info("Tool called: airtable_list_records base=%s table=%s", base_id, table)
        svc = ApiServiceAirtableRecords(CONFIG)
        result = svc.list_records(
            base_id=base_id, table=table, view=view,
            filter_by_formula=filter_by_formula, max_records=max_records,
            page_size=page_size, sort=sort, fields=fields, offset=offset,
        )
        out = {
            "records": [r.__dict__ for r in (result.records or [])],
            "offset": result.offset,
            "count": len(result.records or []),
        }
        logger.info("airtable_list_records returned %d record(s) offset=%s",
                    out["count"], result.offset)
        return out

    @mcp.tool()
    def airtable_list_all_records(
        base_id: str,
        table: str,
        view: Optional[str] = None,
        filter_by_formula: Optional[str] = None,
        max_records: Optional[int] = None,
        sort: Optional[List[Dict[str, str]]] = None,
        fields: Optional[List[str]] = None,
    ) -> list:
        """Fetch ALL matching records, auto-paginating through every page.

        Args:
            base_id:           Base id.
            table:             Table id or name.
            view:              Restrict to records visible in this view.
            filter_by_formula: Airtable formula expression.
            max_records:       Hard cap on total records returned.
            sort:              List of {field, direction} dicts.
            fields:            Only return these field names.
        """
        logger.info("Tool called: airtable_list_all_records base=%s table=%s", base_id, table)
        svc = ApiServiceAirtableRecords(CONFIG)
        result = svc.list_all_records(
            base_id=base_id, table=table, view=view,
            filter_by_formula=filter_by_formula, max_records=max_records,
            sort=sort, fields=fields,
        )
        result = result if isinstance(result, list) else []
        logger.info("airtable_list_all_records returned %d record(s)", len(result))
        return [r.__dict__ for r in result]

    @mcp.tool()
    def airtable_get_record(base_id: str, table: str, record_id: str) -> dict:
        """Fetch a single record by id.

        Args:
            base_id:   Base id.
            table:     Table id or name.
            record_id: Record id, e.g. 'recXXXXXXXX'.
        """
        logger.info("Tool called: airtable_get_record id=%s", record_id)
        svc = ApiServiceAirtableRecords(CONFIG)
        result = svc.get_record(base_id=base_id, table=table, record_id=record_id)
        return result.__dict__

    @mcp.tool()
    def airtable_create_records(
        base_id: str,
        table: str,
        records: List[Dict[str, Any]],
        typecast: bool = False,
    ) -> list:
        """Create up to 10 records in a table.

        Args:
            base_id:  Base id.
            table:    Table id or name.
            records:  List of field-dicts, e.g. [{"Name": "Alice", "Age": 30}].
            typecast: Allow Airtable to coerce strings to the field's type.
        """
        logger.info("Tool called: airtable_create_records count=%d", len(records))
        svc = ApiServiceAirtableRecords(CONFIG)
        result = svc.create_records(
            base_id=base_id, table=table, records=records, typecast=typecast
        )
        result = result if isinstance(result, list) else []
        logger.info("airtable_create_records created %d record(s)", len(result))
        return [r.__dict__ for r in result]

    @mcp.tool()
    def airtable_update_records(
        base_id: str,
        table: str,
        records: List[Dict[str, Any]],
        typecast: bool = False,
        replace: bool = False,
    ) -> list:
        """Update up to 10 records.

        Each item must be `{"id": "rec...", "fields": {...}}`.

        Args:
            base_id:  Base id.
            table:    Table id or name.
            records:  List of `{id, fields}` dicts.
            typecast: Allow Airtable to coerce strings to the field's type.
            replace:  When True, fully replace records (PUT) instead of merging fields (PATCH).
        """
        logger.info("Tool called: airtable_update_records count=%d replace=%s",
                    len(records), replace)
        svc = ApiServiceAirtableRecords(CONFIG)
        result = svc.update_records(
            base_id=base_id, table=table, records=records,
            typecast=typecast, replace=replace,
        )
        result = result if isinstance(result, list) else []
        logger.info("airtable_update_records updated %d record(s)", len(result))
        return [r.__dict__ for r in result]

    @mcp.tool()
    def airtable_upsert_records(
        base_id: str,
        table: str,
        records: List[Dict[str, Any]],
        merge_on: List[str],
        typecast: bool = False,
    ) -> dict:
        """Upsert up to 10 records — match existing rows on `merge_on` fields.

        Args:
            base_id:  Base id.
            table:    Table id or name.
            records:  List of `{"fields": {...}}` dicts.
            merge_on: Field names that uniquely identify an existing row.
            typecast: Allow Airtable to coerce strings to the field's type.
        """
        logger.info("Tool called: airtable_upsert_records count=%d merge_on=%s",
                    len(records), merge_on)
        svc = ApiServiceAirtableRecords(CONFIG)
        result = svc.upsert_records(
            base_id=base_id, table=table, records=records,
            merge_on=merge_on, typecast=typecast,
        )
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def airtable_delete_records(base_id: str, table: str, record_ids: List[str]) -> dict:
        """Delete up to 10 records by id.

        Args:
            base_id:    Base id.
            table:      Table id or name.
            record_ids: List of record ids to delete.
        """
        logger.info("Tool called: airtable_delete_records count=%d", len(record_ids))
        svc = ApiServiceAirtableRecords(CONFIG)
        result = svc.delete_records(base_id=base_id, table=table, record_ids=record_ids)
        logger.info("airtable_delete_records done")
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def airtable_create_table(
        base_id: str,
        name: str,
        fields: List[Dict[str, Any]],
        description: Optional[str] = None,
    ) -> dict:
        """Create a new table in a base.

        Args:
            base_id:     Base id.
            name:        Table name.
            fields:      List of field definitions, each at minimum `{name, type}`.
                         The first field becomes the primary field.
            description: Optional table description.
        """
        logger.info("Tool called: airtable_create_table name=%s", name)
        svc = ApiServiceAirtableTables(CONFIG)
        result = svc.create_table(
            base_id=base_id, name=name, fields=fields, description=description
        )
        d = result.__dict__.copy()
        d["fields"] = [f.__dict__ for f in (result.fields or [])]
        d["views"] = [v.__dict__ for v in (result.views or [])]
        return d

    @mcp.tool()
    def airtable_create_field(
        base_id: str,
        table_id: str,
        name: str,
        type: str,
        options: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
    ) -> dict:
        """Add a new field to an existing table.

        Args:
            base_id:     Base id.
            table_id:    Table id (must be the id, not the name).
            name:        Field name.
            type:        Field type, e.g. 'singleLineText', 'number', 'singleSelect',
                         'date', 'checkbox', 'multipleAttachments'.
            options:     Type-specific options dict (required for some types).
            description: Optional field description.
        """
        logger.info("Tool called: airtable_create_field name=%s type=%s", name, type)
        svc = ApiServiceAirtableTables(CONFIG)
        result = svc.create_field(
            base_id=base_id, table_id=table_id, name=name, type=type,
            options=options, description=description,
        )
        return result.__dict__
