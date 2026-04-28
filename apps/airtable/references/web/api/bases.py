"""Airtable Bases service — list bases, fetch user info."""
from typing import List

from apps.airtable.references.web.base_api_service import BaseApiServiceAirtable
from apps.airtable.references.dto.bases import DtoAirtableBase, DtoAirtableUser


class ApiServiceAirtableBases(BaseApiServiceAirtable):
    """Airtable bases + whoami."""

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    def list_bases(self) -> List[DtoAirtableBase]:
        """List all bases the authenticated PAT has access to."""
        data = self._get("/meta/bases")
        return [
            DtoAirtableBase(
                id=b.get("id"),
                name=b.get("name"),
                permissionLevel=b.get("permissionLevel"),
            )
            for b in (data.get("bases") or [])
        ]

    def whoami(self) -> DtoAirtableUser:
        """Return information about the authenticated user/PAT."""
        data = self._get("/meta/whoami")
        return DtoAirtableUser(
            id=data.get("id"),
            email=data.get("email"),
            scopes=data.get("scopes"),
        )
