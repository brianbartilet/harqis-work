from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from core.web.services.core.decorators.deserializer import deserialized

from apps.hfl_corpus.references.dto.entries import DtoHflCorpusEntryResult
from apps.hfl_corpus.references.web.base_api_service import BaseApiServiceHflCorpus


class ApiServiceHflCorpusEntries(BaseApiServiceHflCorpus):
    """Create and preview canonical Homework-for-Life entries."""

    @staticmethod
    def _payload(
        date: str,
        time: str,
        moment: str,
        what_happened: str,
        why_it_stayed: str = "",
        possible_use: str = "",
        source: str = "manual-entry",
        tags: str = "",
        references: str = "",
        attachment_names: Optional[list[str]] = None,
        include_location: bool = True,
        browser_latitude: Optional[float] = None,
        browser_longitude: Optional[float] = None,
        browser_location_status: str = "",
    ) -> dict:
        return {
            "date": date,
            "time": time,
            "moment": moment,
            "what_happened": what_happened,
            "why_it_stayed": why_it_stayed,
            "possible_use": possible_use,
            "source": source,
            "tags": tags,
            "references": references,
            "attachment_names": attachment_names or [],
            "include_location": include_location,
            "browser_latitude": browser_latitude,
            "browser_longitude": browser_longitude,
            "browser_location_status": browser_location_status,
        }

    @deserialized(DtoHflCorpusEntryResult)
    def create_entry(
        self,
        date: str,
        time: str,
        moment: str,
        what_happened: str,
        why_it_stayed: str = "",
        possible_use: str = "",
        source: str = "manual-entry",
        tags: str = "",
        references: str = "",
        include_location: bool = True,
        browser_latitude: Optional[float] = None,
        browser_longitude: Optional[float] = None,
        browser_location_status: str = "",
    ) -> DtoHflCorpusEntryResult:
        """Persist one entry to Markdown and its Elasticsearch projection."""
        payload = self._payload(
            date, time, moment, what_happened, why_it_stayed, possible_use,
            source, tags, references, include_location=include_location,
            browser_latitude=browser_latitude,
            browser_longitude=browser_longitude,
            browser_location_status=browser_location_status,
        )
        self.request.post().add_uri_parameter("entries").add_json_payload(payload)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def preview_entry(
        self,
        date: str,
        time: str,
        moment: str,
        what_happened: str,
        why_it_stayed: str = "",
        possible_use: str = "",
        source: str = "manual-entry",
        tags: str = "",
        references: str = "",
        include_location: bool = True,
        browser_latitude: Optional[float] = None,
        browser_longitude: Optional[float] = None,
        browser_location_status: str = "",
    ) -> dict:
        """Render and enrich an entry without persisting it."""
        payload = self._payload(
            date, time, moment, what_happened, why_it_stayed, possible_use,
            source, tags, references, include_location=include_location,
            browser_latitude=browser_latitude,
            browser_longitude=browser_longitude,
            browser_location_status=browser_location_status,
        )
        self.request.post() \
            .add_uri_parameter("entries") \
            .add_uri_parameter("preview") \
            .add_json_payload(payload)
        return self.client.execute_request(self.request.build())

    def create_entry_with_uploads(
        self,
        date: str,
        time: str,
        moment: str,
        what_happened: str,
        file_paths: list[str],
        why_it_stayed: str = "",
        possible_use: str = "",
        source: str = "manual-entry",
        tags: str = "",
        references: str = "",
        include_location: bool = True,
    ) -> dict:
        """Persist an entry and upload up to 50 local attachment files."""
        paths = [Path(value).expanduser().resolve() for value in file_paths]
        missing = [str(path) for path in paths if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"Attachment files not found: {', '.join(missing)}")
        payload = self._payload(
            date, time, moment, what_happened, why_it_stayed, possible_use,
            source, tags, references,
            attachment_names=[path.name for path in paths],
            include_location=include_location,
        )
        handles = [path.open("rb") for path in paths]
        try:
            files = [
                ("files", (path.name, handle, "application/octet-stream"))
                for path, handle in zip(paths, handles)
            ]
            response = self._raw_request(
                "POST",
                "entries/upload",
                data={"payload": json.dumps(payload)},
                files=files,
                timeout=max(self.client.timeout, 300),
            )
            result = response.json()
            return result if isinstance(result, dict) else {}
        finally:
            for handle in handles:
                handle.close()
