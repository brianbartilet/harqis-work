from __future__ import annotations

from typing import Optional, Dict, Any, List

from apps.google_apps.references.web.discovery import BaseGoogleDiscoveryService


class ApiServiceGoogleKeepNotes(BaseGoogleDiscoveryService):
    """
    Google Keep notes service using the discovery API.

    Wraps keep.googleapis.com v1:
      - notes().list(...)
      - notes().get(...)
      - notes().create(...)
      - notes().delete(...)

    Docs:
      - Discovery: https://keep.googleapis.com/$discovery/rest?version=v1
      - REST:      https://developers.google.com/workspace/keep/api/reference/rest/v1/notes
    """

    SERVICE_NAME = "keep"
    SERVICE_VERSION = "v1"

    def __init__(self, config, **kwargs) -> None:
        """
        Args:
            config: your apps.google_apps.config.CONFIG or similar
        """
        super().__init__(config, **kwargs)
        self.notes_resource = self.service.notes()

    # ------------------------------------------------------------------ #
    # Low-level wrappers
    # ------------------------------------------------------------------ #

    def list_notes(
        self,
        filter: Optional[str] = None,
        page_size: int = 100,
        page_token: Optional[str] = None,
        **extra_query: Any,
    ) -> Dict[str, Any]:
        """
        Wraps keep.notes().list(...)

        Args:
            filter:
                AIP-160-style filter string.
                If omitted, the API applies a default `trashed` filter (trashed=false). :contentReference[oaicite:0]{index=0}
                Valid fields include: create_time, update_time, trash_time, trashed.
            page_size:
                Max number of notes per page (0 lets server choose upper bound). :contentReference[oaicite:1]{index=1}
            page_token:
                Token from previous response["nextPageToken"] to fetch the next page. :contentReference[oaicite:2]{index=2}
            extra_query:
                Any extra query params supported by the API.

        Returns:
            Full ListNotesResponse dict, including:
              - "notes": [ ... ]
              - "nextPageToken": str | None
        """
        params: Dict[str, Any] = {}
        if filter is not None:
            params["filter"] = filter
        if page_size is not None:
            params["pageSize"] = page_size
        if page_token:
            params["pageToken"] = page_token

        params.update(extra_query)

        return self.notes_resource.list(**params).execute()

    def get_note(self, name: str) -> Dict[str, Any]:
        """
        Wraps keep.notes().get(...)

        Args:
            name: Resource name, e.g. "notes/NOTE_ID".

        Returns:
            Note resource dict.
        """
        return self.notes_resource.get(name=name).execute()

    def create_note(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """
        Wraps keep.notes().create(...)

        Args:
            body:
                Note payload as per API schema, e.g.:
                {
                  "title": "My Note",
                  "body": {
                    "text": {
                      "text": "Hello Keep!"
                    }
                  }
                }

        Returns:
            Created note resource dict.
        """
        return self.notes_resource.create(body=body).execute()

    def delete_note(self, name: str) -> None:
        """
        Wraps keep.notes().delete(...)

        Args:
            name: Resource name, e.g. "notes/NOTE_ID".
        """
        self.notes_resource.delete(name=name).execute()

    # ------------------------------------------------------------------ #
    # Convenience helpers
    # ------------------------------------------------------------------ #

    def list_all_notes(
        self,
        filter: Optional[str] = None,
        page_size: int = 100,
        **extra_query: Any,
    ) -> List[Dict[str, Any]]:
        """
        Fetches *all* notes for the given filter, handling pagination.

        Args:
            filter: Same as list_notes().
            page_size: Page size for each backend call.
            extra_query: Extra query params for notes().list().

        Returns:
            Flat list of note dicts.
        """
        all_notes: List[Dict[str, Any]] = []
        next_token: Optional[str] = None

        while True:
            resp = self.list_notes(
                filter=filter,
                page_size=page_size,
                page_token=next_token,
                **extra_query,
            )
            all_notes.extend(resp.get("notes", []))
            next_token = resp.get("nextPageToken")
            if not next_token:
                break

        return all_notes

    def list_non_trashed_notes(
        self,
        page_size: int = 100,
        **extra_query: Any,
    ) -> List[Dict[str, Any]]:
        """
        Convenience: return all non-trashed notes.

        Explicitly sets `trashed=false` in the filter.
        """
        filter_expr = "trashed=false"
        return self.list_all_notes(filter=filter_expr, page_size=page_size, **extra_query)
