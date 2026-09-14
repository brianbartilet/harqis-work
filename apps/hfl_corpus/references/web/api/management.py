"""Bearer-authenticated action, category, and date-pin commands."""
from urllib.parse import quote

from core.web.services.core.decorators.deserializer import deserialized

from apps.hfl_corpus.references.web.base_api_service import BaseApiServiceHflCorpus


class ApiServiceHflCorpusManagement(BaseApiServiceHflCorpus):
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
                      notes: str = "", source: dict | None = None) -> dict:
        """Create intent without scheduled agent execution; reuse request_id on retry."""
        return self._command("post", "actions", payload={
            "request_id": request_id, "title": title, "expected_outcome": expected_outcome,
            "review_date": review_date, "due_date": due_date, "prompt": prompt,
            "notes": notes, "source": source,
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
