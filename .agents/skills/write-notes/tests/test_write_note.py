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
