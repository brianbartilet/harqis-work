"""Base service for AppSheet API v2.

Auth: per-app ApplicationAccessKey header (generated in the AppSheet app's
*Manage → Integrations* tab; integrations must be enabled there first).

Every endpoint is POST against:
    https://api.appsheet.com/api/v2/apps/{appId}/tables/{tableName}/Action

The body always has the shape:
    {"Action": "<Add|Edit|Delete|Find>",
     "Properties": {"Locale": "en-US", ...},
     "Rows": [...]}

Docs: https://support.google.com/appsheet/answer/10105768
"""
from typing import Any, Optional

import httpx

from core.web.services.fixtures.rest import BaseFixtureServiceRest


class BaseApiServiceAppSheet(BaseFixtureServiceRest):
    """Base service for AppSheet REST API.

    Provides an `_action()` helper that POSTs to the table-Action endpoint
    with the access-key header and standard body envelope.
    """

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self._access_key: str = config.app_data["application_access_key"]
        self._default_app_id: Optional[str] = config.app_data.get("default_app_id")
        self.default_table: Optional[str] = config.app_data.get("default_table")
        self._default_locale: str = config.app_data.get("locale", "en-US")
        self._timeout: int = int(config.parameters.get("timeout", 60))
        # Trim trailing slash so f-string concatenation produces a single slash.
        base = (config.parameters.get("base_url") or "").rstrip("/")
        self._base_url = base or "https://api.appsheet.com/api/v2"

        self._headers = {
            "ApplicationAccessKey": self._access_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _resolve_app_id(self, app_id: Optional[str]) -> str:
        resolved = app_id or self._default_app_id
        if not resolved:
            raise ValueError(
                "AppSheet app_id is required — pass app_id=... or set "
                "default_app_id in the APPSHEET section of apps_config.yaml."
            )
        return resolved

    def _action(
        self,
        table_name: str,
        action: str,
        rows: Optional[list[dict[str, Any]]] = None,
        properties: Optional[dict[str, Any]] = None,
        app_id: Optional[str] = None,
    ) -> Any:
        """POST one Action call to AppSheet.

        AppSheet returns either a JSON list (Find / Add / Edit) or a body that
        may be empty or non-JSON (Delete). Callers get the parsed JSON when
        possible, otherwise the raw text.
        """
        resolved_app_id = self._resolve_app_id(app_id)
        url = f"{self._base_url}/apps/{resolved_app_id}/tables/{table_name}/Action"
        props = {"Locale": self._default_locale}
        if properties:
            props.update(properties)
        body = {
            "Action": action,
            "Properties": props,
            "Rows": rows or [],
        }
        resp = httpx.post(url, headers=self._headers, json=body, timeout=self._timeout)
        resp.raise_for_status()
        if not resp.content:
            return []
        try:
            return resp.json()
        except ValueError:
            return resp.text
