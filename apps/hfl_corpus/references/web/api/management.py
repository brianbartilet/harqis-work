"""Bearer-authenticated action, category, and date-pin commands."""
from urllib.parse import quote
from contextlib import ExitStack
from pathlib import Path

from core.web.services.core.decorators.deserializer import deserialized

from apps.hfl_corpus.references.web.base_api_service import BaseApiServiceHflCorpus


class ApiServiceHflCorpusManagement(BaseApiServiceHflCorpus):
    @staticmethod
    def _attachment_endpoint(resource, source_id, attachment_id=None):
        if resource not in {'actions', 'pins'}:
            raise ValueError('Choose actions or pins.')
        endpoint = f'{resource}/{quote(str(source_id), safe="")}/attachments'
        return endpoint + ('/' + quote(attachment_id, safe='') if attachment_id else '')

    def upload_attachments(self, resource: str, source_id: str, file_paths: list[str]) -> dict:
        """Upload task inputs. Identical names/content are deduplicated on retry."""
        endpoint = self._attachment_endpoint(resource, source_id)
        paths = [Path(value).expanduser().resolve() for value in file_paths]
        if not 1 <= len(paths) <= 10 or any(not p.is_file() or p.stat().st_size > 50 * 1024 * 1024 for p in paths):
            raise ValueError('Choose 1–10 regular files, at most 50 MB each.')
        if sum(p.stat().st_size for p in paths) > 200 * 1024 * 1024:
            raise ValueError('Attachments exceed 200 MB total.')
        with ExitStack() as stack:
            files = [('files', (p.name, stack.enter_context(p.open('rb')), 'application/octet-stream')) for p in paths]
            return self._raw_request('POST', endpoint, files=files).json()

    def list_attachments(self, resource: str, source_id: str) -> dict:
        return self._raw_request('GET', self._attachment_endpoint(resource, source_id)).json()

    def download_attachment(self, resource: str, source_id: str, attachment_id: str, destination: str) -> dict:
        return self._download(self._attachment_endpoint(resource, source_id, attachment_id), destination)

    def delete_attachment(self, resource: str, source_id: str, attachment_id: str) -> dict:
        return self._raw_request('DELETE', self._attachment_endpoint(resource, source_id, attachment_id)).json()

    @deserialized(dict)
    def _command(self, method, resource, record_id=None, suffix=None, payload=None, **query):
        getattr(self.request, method)().add_uri_parameter(resource)
        if record_id is not None:
            self.request.add_uri_parameter(quote(str(record_id), safe=""))
        if suffix:
            self.request.add_uri_parameter(suffix)
        if payload is not None:
            self.request.add_json_payload(payload)
        if query:
            self.request.add_query_strings(**query)
        return self.client.execute_request(self.request.build())

    def create_action(self, request_id: str, title: str, expected_outcome: str,
                      review_date: str = "", due_date: str = "", prompt: str = "",
                      notes: str = "", source: dict | None = None,
                      matrix: str = "", matrix_confidence: str = "", matrix_reason: str = "") -> dict:
        """Create intent without scheduled agent execution; reuse request_id on retry."""
        return self._command("post", "actions", payload={
            "request_id": request_id, "title": title, "expected_outcome": expected_outcome,
            "review_date": review_date, "due_date": due_date, "prompt": prompt,
            "notes": notes, "source": source,
            "matrix": matrix, "matrix_confidence": matrix_confidence, "matrix_reason": matrix_reason,
        })

    def list_actions(self, closed: bool = False, offset: int = 0) -> dict:
        """List up to 500 actions per call."""
        return self._command("get", "actions", closed=str(closed).lower(), offset=offset)

    def get_action(self, action_id: str) -> dict:
        return self._command("get", "actions", action_id)

    def update_action(self, action_id: str, version: int, changes: dict) -> dict:
        """Partial edit; status=done completes, status=dismissed dismisses."""
        return self._command("patch", "actions", action_id, payload={**changes, "version": version})

    def get_action_history(self, action_id: str) -> dict:
        return self._command("get", "actions", action_id, "history")

    def create_category(self, name: str, color: str, instructions: str = "") -> dict:
        return self._command("post", "categories", payload={"name": name, "color": color, "instructions": instructions})

    def list_categories(self) -> dict:
        return self._command("get", "categories")

    def get_category(self, category_id: int) -> dict:
        return self._command("get", "categories", category_id)

    def update_category(self, category_id: int, changes: dict) -> dict:
        return self._command("patch", "categories", category_id, payload=changes)

    def archive_category(self, category_id: int) -> dict:
        return self._command("post", "categories", category_id, "archive")

    def create_pin(self, category_id: int, start_date: str, end_date: str, title: str,
                   note: str = "", prompt: str = "") -> dict:
        return self._command("post", "pins", payload={
            "category_id": category_id, "start_date": start_date, "end_date": end_date,
            "title": title, "note": note, "prompt": prompt,
        })

    def list_pins(self, category_id: int | None = None) -> dict:
        return self._command("get", "pins", **({"category_id": category_id} if category_id is not None else {}))

    def get_pin(self, pin_id: int) -> dict:
        return self._command("get", "pins", pin_id)

    def update_pin(self, pin_id: int, changes: dict) -> dict:
        return self._command("patch", "pins", pin_id, payload=changes)

    def delete_pin(self, pin_id: int) -> dict:
        return self._command("delete", "pins", pin_id)
