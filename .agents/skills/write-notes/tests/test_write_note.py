from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "write_note.py"
SPEC = importlib.util.spec_from_file_location("write_notes_helper", MODULE_PATH)
assert SPEC and SPEC.loader
write_note = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(write_note)


def _payload(**changes):
    payload = {
        "date": "2026-08-20",
        "time": "14:30",
        "moment": "Renew workshop subscription",
        "what_happened": "Renew the subscription before Friday.",
        "why_it_stayed": "The deadline is close.",
        "possible_use": "Complete the renewal.",
        "tags": ["Admin", "#notes", "admin"],
        "references": ["https://example.com/account"],
        "is_reminder": True,
    }
    payload.update(changes)
    return payload


class FakeService:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = []

    def create_entry(self, **payload):
        self.calls.append(("create", payload))
        if self.fail:
            raise ConnectionError("offline")
        return {
            "entry_id": "hfl-test",
            "path": "/corpus/2026-08-20.md",
            "duplicate": False,
            "indexed": True,
            "delivery": "persisted",
        }

    def create_entry_with_uploads(self, *, file_paths, **payload):
        self.calls.append(("upload", payload, file_paths))
        if self.fail:
            raise ConnectionError("offline")
        return {
            "entry_id": "hfl-upload",
            "path": "/corpus/2026-08-20.md",
            "duplicate": False,
            "indexed": True,
            "delivery": "persisted",
            "uploads": [Path(value).name for value in file_paths],
        }


def _canonical_note(
    *,
    guid="hfl-note-123",
    timestamp="2026-08-22 01:34",
    what_happened="Captured the original thought.",
):
    body = (
        "Source:          notes\n"
        "Machine:         windows-work-all\n"
        f"Entry ID:        {guid}\n"
        "Moment:          Original note\n"
        f"What happened:   {what_happened}\n"
        "Why it stayed:   It may be useful.\n"
        "Possible use:    Review it later.\n"
        "Tags:            #manual-entry #notes #idea\n\n"
    )
    item = {
        "anchor": "hfl-entry-1-2026-08-22-01-34",
        "header": timestamp,
        "moment": "Original note",
        "what_happened": what_happened,
        "source": "notes",
        "text": f"{timestamp}\n{body}",
    }
    return item, f"# Homework for Life\n\n## {timestamp}\n{body}"


class FakeDocumentService:
    def __init__(self):
        self.item, self.text = _canonical_note()
        self.updated_at = "2026-08-22T01:35:00+08:00"
        self.updated_text = None
        self.calls = []

    def list_documents(self, **kwargs):
        self.calls.append(("list", kwargs))
        return {
            "results": [{"relative_path": "2026-08-22.md"}],
            "selected_source": "notes",
        }

    def list_matches(self, relative_path, **kwargs):
        self.calls.append(("matches", relative_path, kwargs))
        return {"entries": [self.item], "total": 1}

    def get_document(self, relative_path, **kwargs):
        self.calls.append(("get", relative_path, kwargs))
        return {
            "document": {
                "relative_path": relative_path,
                "updated_at": self.updated_at,
                "text": self.text,
                "entries": [self.item],
            }
        }

    def update_document(self, relative_path, text):
        self.calls.append(("update", relative_path))
        self.updated_text = text
        return {"updated": True, "relative_path": relative_path, "size": len(text)}


def test_prepare_payload_applies_skill_invariants():
    result = write_note.prepare_payload(_payload())

    assert result["source"] == "notes"
    assert result["include_location"] is False
    assert result["tags"] == "#manual-entry #notes #reminders #admin"
    assert result["references"] == "https://example.com/account"


def test_prepare_payload_rejects_non_http_reference():
    with pytest.raises(ValueError, match=r"HTTP\(S\)"):
        write_note.prepare_payload(_payload(references=["file:///private/note.txt"]))


def test_missing_attachment_prevents_service_call(tmp_path):
    service = FakeService()

    with pytest.raises(ValueError, match="missing or unreadable"):
        write_note.submit_or_outbox(
            _payload(),
            [str(tmp_path / "missing.jpg")],
            web_url="https://notes.example.test",
            outbox_root=tmp_path / "outbox",
            service_factory=lambda: service,
        )

    assert service.calls == []


def test_analyze_image_cleans_and_bounds_local_ocr(tmp_path):
    from PIL import Image

    image = tmp_path / "receipt.png"
    Image.new("RGB", (20, 20), "white").save(image)

    result = write_note.analyze_images(
        [str(image)],
        max_chars=20,
        ocr_func=lambda _image: "  TOTAL  $12.00  \r\n\r\n\r\n Thank you for shopping here today ",
    )["images"][0]

    assert result["status"] == "ok"
    assert result["ocr_text"] == "TOTAL  $12.00"
    assert result["characters"] > len(result["ocr_text"])
    assert result["truncated"] is True


def test_analyze_image_reports_ocr_failure_without_raising(tmp_path):
    from PIL import Image

    image = tmp_path / "damaged-text.jpg"
    Image.new("RGB", (20, 20), "white").save(image)

    def fail(_image):
        raise RuntimeError("OCR unavailable")

    result = write_note.analyze_images(
        [str(image)], ocr_func=fail
    )["images"][0]

    assert result["status"] == "error"
    assert result["ocr_text"] == ""
    assert result["error_type"] == "RuntimeError"


def test_analyze_image_marks_unsupported_file_for_upload(tmp_path):
    attachment = tmp_path / "diagram.svg"
    attachment.write_text("<svg/>", encoding="utf-8")

    result = write_note.analyze_images([str(attachment)])["images"][0]

    assert result["status"] == "unsupported"
    assert result["ocr_text"] == ""


def test_submit_returns_document_link_and_uploads(tmp_path):
    attachment = tmp_path / "photo one.jpg"
    attachment.write_bytes(b"image")
    service = FakeService()

    output, code = write_note.submit_or_outbox(
        _payload(),
        [str(attachment)],
        web_url="https://notes.example.test",
        outbox_root=tmp_path / "outbox",
        service_factory=lambda: service,
    )

    assert code == 0
    assert output["status"] == "submitted"
    assert output["document_url"] == (
        "https://notes.example.test/hfl-corpus/document/2026-08-20.md"
    )
    assert service.calls[0][0] == "upload"


def test_recent_notes_returns_table_ready_rows_and_latest_url():
    service = FakeDocumentService()

    output = write_note.recent_notes(
        limit=10,
        web_url="https://notes.example.test",
        service_factory=lambda: service,
    )

    assert output["status"] == "recent"
    assert output["notes"] == [{
        "guid": "hfl-note-123",
        "what_happened": "Captured the original thought.",
        "timestamp": "2026-08-22 01:34",
        "document_hfl": (
            "https://notes.example.test/hfl-corpus/document/2026-08-22.md"
            "#hfl-entry-1-2026-08-22-01-34"
        ),
    }]
    assert output["latest_document_url"] == output["notes"][0]["document_hfl"]
    assert service.calls[0][1]["compact"] is True
    assert service.calls[0][1]["source"] == "notes"
    assert service.calls[0][1]["query"] == "#manual-entry"


def test_recent_notes_excludes_automated_source_notes_entries():
    service = FakeDocumentService()
    service.item["text"] = service.item["text"].replace(
        "#manual-entry #notes #idea", "#notes #repo-work #idea"
    )

    output = write_note.recent_notes(
        limit=10,
        web_url="https://notes.example.test",
        service_factory=lambda: service,
    )

    assert output["notes"] == []
    assert output["latest_document_url"] is None


def test_get_note_returns_editable_fields_and_revision_token():
    service = FakeDocumentService()

    output = write_note.get_note(
        "hfl-note-123",
        web_url="https://notes.example.test",
        service_factory=lambda: service,
    )

    assert output["status"] == "found"
    assert output["note"]["guid"] == "hfl-note-123"
    assert output["note"]["what_happened"] == "Captured the original thought."
    assert output["note"]["document_updated_at"] == service.updated_at


def test_update_note_replaces_only_selected_guid_and_reindexes():
    service = FakeDocumentService()
    indexed = []

    output = write_note.update_note(
        "hfl-note-123",
        {"what_happened": "Captured the revised thought."},
        expected_updated_at=service.updated_at,
        web_url="https://notes.example.test",
        service_factory=lambda: service,
        index_func=lambda entry: indexed.append(entry) or entry.entry_id,
    )

    assert output["status"] == "updated"
    assert output["before"]["what_happened"] == "Captured the original thought."
    assert output["after"]["what_happened"] == "Captured the revised thought."
    assert output["result"]["entry_id"] == "hfl-note-123"
    assert output["result"]["indexed"] is True
    assert "Entry ID:        hfl-note-123" in service.updated_text
    assert "What happened:   Captured the revised thought." in service.updated_text
    assert "Captured the original thought." not in service.updated_text
    assert indexed[0].entry_id == "hfl-note-123"
    assert indexed[0].when.strftime("%Y-%m-%d %H:%M") == "2026-08-22 01:34"


def test_update_note_refuses_a_stale_document_revision():
    service = FakeDocumentService()

    with pytest.raises(ValueError, match="changed after review"):
        write_note.update_note(
            "hfl-note-123",
            {"moment": "Revised note"},
            expected_updated_at="2026-08-22T01:34:00+08:00",
            web_url="https://notes.example.test",
            service_factory=lambda: service,
            index_func=lambda entry: entry.entry_id,
        )

    assert service.updated_text is None


def test_failure_saves_credential_free_outbox_and_retry_removes_it(tmp_path):
    outbox = tmp_path / "outbox"
    failed_service = FakeService(fail=True)
    output, code = write_note.submit_or_outbox(
        _payload(),
        [],
        web_url="https://notes.example.test",
        outbox_root=outbox,
        service_factory=lambda: failed_service,
    )

    assert code == 1
    path = Path(output["outbox"])
    record = json.loads(path.read_text(encoding="utf-8"))
    assert "token" not in json.dumps(record).casefold()
    assert "error" not in record

    retry_output, retry_code = write_note.retry_items(
        outbox,
        [str(path)],
        service_factory=lambda: FakeService(),
    )
    assert retry_code == 0
    assert retry_output["items"][0]["status"] == "submitted"
    assert not path.exists()
