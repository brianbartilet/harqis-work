"""Tests for the Plaud acquisition adapter.

The folder backend is exercised fully with a temp directory (no credentials
needed). The cloud backend's field-mapping (api.plaud.ai JSON → DTO) and the
token mint/cache/refresh lifecycle are unit tested offline with mocked HTTP;
its live listing is an integration check skipped unless PLAUD_TOKEN is set.
"""
import base64
import json
import os
import time

import pytest
from hamcrest import assert_that, equal_to, instance_of, not_none

from apps.plaud.references.dto.recording import DtoPlaudRecording
from apps.plaud.references.adapter import (
    PlaudAdapter,
    PlaudCloudBackend,
    PlaudFolderBackend,
    build_adapter,
)


@pytest.fixture()
def export_dir(tmp_path):
    """A fake Plaud export folder: one audio file with a sibling transcript
    and a sibling summary."""
    (tmp_path / "2026-06-08 Standup.mp3").write_bytes(b"\x00\x00")
    (tmp_path / "2026-06-08 Standup.txt").write_text("Full transcript here.", encoding="utf-8")
    (tmp_path / "2026-06-08 Standup-summary.md").write_text("Short summary.", encoding="utf-8")
    return str(tmp_path)


@pytest.mark.smoke
def test_folder_backend_lists_and_pairs_sidecars(export_dir):
    backend = PlaudFolderBackend(export_dir)
    assert_that(backend.available(), equal_to(True))

    recs = backend.list_recordings()
    assert_that(recs, instance_of(list))
    assert_that(len(recs), equal_to(1))

    rec = recs[0]
    assert_that(rec.id, not_none())
    assert_that(rec.title, equal_to("2026-06-08 Standup"))
    assert_that(rec.origin, equal_to("folder"))
    assert_that(rec.has_transcript, equal_to(True))
    assert_that(rec.transcript, equal_to("Full transcript here."))
    assert_that(rec.summary, equal_to("Short summary."))
    assert_that(rec.audio_path, not_none())


@pytest.mark.smoke
def test_folder_backend_id_is_deterministic(export_dir):
    a = PlaudFolderBackend(export_dir).list_recordings()[0]
    b = PlaudFolderBackend(export_dir).list_recordings()[0]
    assert_that(a.id, equal_to(b.id))  # idempotent across runs → ES upsert, not dupe


@pytest.mark.smoke
def test_adapter_falls_back_to_folder_when_no_token(export_dir):
    adapter = PlaudAdapter(PlaudCloudBackend(token=""), PlaudFolderBackend(export_dir))
    status = adapter.status
    assert_that(status["cloud_ready"], equal_to(False))
    assert_that(status["folder_ready"], equal_to(True))
    assert_that(status["active"], equal_to("folder"))

    recs = adapter.list_recordings()
    assert_that(len(recs), equal_to(1))


@pytest.mark.smoke
def test_empty_when_neither_backend_ready():
    adapter = PlaudAdapter(PlaudCloudBackend(token=""), PlaudFolderBackend(export_dir=""))
    assert_that(adapter.list_recordings(), equal_to([]))
    assert_that(adapter.status["active"], equal_to(None))


@pytest.mark.smoke
def test_cloud_normalize_maps_real_api_fields():
    """A representative api.plaud.ai /file/simple/web record maps onto the DTO."""
    item = {
        "file_id": "abc123",
        "filename": "Team sync",
        "start_time": 1749427200,  # epoch seconds → 2025-06-09T00:00:00Z
        "duration": 612,
        "filesize": 9000000,
    }
    rec = PlaudCloudBackend._normalize(item)
    assert_that(rec.id, equal_to("abc123"))
    assert_that(rec.title, equal_to("Team sync"))
    assert_that(rec.origin, equal_to("cloud"))
    assert_that(rec.duration_seconds, equal_to(612))
    assert_that(rec.started_at, not_none())
    assert_that(rec.started_at.startswith("2025-06-09T"), equal_to(True))


@pytest.mark.smoke
def test_cloud_normalize_handles_millisecond_epoch():
    rec = PlaudCloudBackend._normalize({"file_id": "x", "start_time": 1749427200000})
    assert_that(rec.started_at.startswith("2025-06-09T"), equal_to(True))


@pytest.mark.smoke
def test_cloud_extract_list_tolerates_envelope_drift():
    extract = PlaudCloudBackend._extract_list
    assert_that(extract({"data_file_list": [{"file_id": "1"}]}), equal_to([{"file_id": "1"}]))
    assert_that(extract([{"file_id": "2"}]), equal_to([{"file_id": "2"}]))
    assert_that(extract({"data": {"list": [{"file_id": "3"}]}}), equal_to([{"file_id": "3"}]))
    assert_that(extract({"status": "ok"}), equal_to([]))


@pytest.mark.smoke
def test_cloud_temp_url_uses_url_extension_when_opus_key_is_empty(monkeypatch):
    backend = PlaudCloudBackend(token="secret")
    monkeypatch.setattr(
        backend,
        "_get",
        lambda *args, **kwargs: {
            "temp_url_opus": None,
            "temp_url": "https://bucket.example/rec.ogg?signature=ok",
        },
    )
    rec = DtoPlaudRecording(id="rec1", title="Recording", audio_format="mp3")

    url = backend._resolve_audio_url(rec)

    assert_that(url, equal_to("https://bucket.example/rec.ogg?signature=ok"))
    assert_that(rec.audio_format, equal_to("ogg"))


@pytest.mark.smoke
def test_cloud_download_uses_clean_client_for_signed_urls(monkeypatch, tmp_path):
    """S3 presigned URLs fail if the Plaud bearer Authorization header leaks in."""

    class _AuthSession:
        def get(self, *args, **kwargs):
            raise AssertionError("signed URL download reused Plaud auth session")

    class _Response:
        status_code = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield b"audio"

    def clean_get(url, **kwargs):
        assert_that(url, equal_to("https://bucket.example/rec.ogg?signature=ok"))
        assert_that("headers" not in kwargs or "Authorization" not in (kwargs.get("headers") or {}), equal_to(True))
        return _Response()

    import requests

    monkeypatch.setattr(requests, "get", clean_get)
    backend = PlaudCloudBackend(token="secret")
    monkeypatch.setattr(backend, "_get_session", lambda: _AuthSession())
    rec = DtoPlaudRecording(
        id="rec1",
        title="Recording",
        audio_url="https://bucket.example/rec.ogg?signature=ok",
        audio_format="ogg",
    )

    path = backend.ensure_audio_local(rec, str(tmp_path))

    assert_that(path, not_none())
    assert_that((tmp_path / "rec1.ogg").read_bytes(), equal_to(b"audio"))


# ── token mint / cache / refresh lifecycle ────────────────────────────────────

def _fake_jwt(exp: float, iat: float | None = None) -> str:
    """Unsigned JWT with just the claims the adapter reads (iat/exp)."""
    payload = base64.urlsafe_b64encode(
        json.dumps({"iat": iat or time.time(), "exp": exp}).encode()
    ).rstrip(b"=").decode()
    return f"eyJhbGciOiJIUzI1NiJ9.{payload}.sig"


class _AuthResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


def _creds_backend(tmp_path, **kwargs) -> PlaudCloudBackend:
    return PlaudCloudBackend(
        token=kwargs.pop("token", ""),
        email="user@example.com",
        password="hunter2",
        token_cache=str(tmp_path / "plaud_token.json"),
        **kwargs,
    )


@pytest.mark.smoke
def test_available_with_credentials_only(tmp_path):
    backend = _creds_backend(tmp_path)
    assert_that(backend.available(), equal_to(True))
    assert_that(backend.auth_mode, equal_to("credentials"))


@pytest.mark.smoke
def test_mint_posts_credentials_and_caches_token(monkeypatch, tmp_path):
    fresh = _fake_jwt(exp=time.time() + 300 * 24 * 3600)
    calls = []

    def fake_post(url, data=None, **kwargs):
        calls.append((url, data))
        return _AuthResponse({"status": 0, "access_token": fresh,
                              "token_type": "Bearer"})

    import requests

    monkeypatch.setattr(requests, "post", fake_post)
    backend = _creds_backend(tmp_path)

    token = backend._resolve_token()

    assert_that(token, equal_to(fresh))
    assert_that(calls[0][0], equal_to("https://api.plaud.ai/auth/access-token"))
    assert_that(calls[0][1], equal_to({"username": "user@example.com",
                                       "password": "hunter2"}))
    cached = json.loads((tmp_path / "plaud_token.json").read_text())
    assert_that(cached["access_token"], equal_to(fresh))
    assert_that(cached["expires_at"], not_none())


@pytest.mark.smoke
def test_valid_cached_token_skips_mint(monkeypatch, tmp_path):
    cached_token = _fake_jwt(exp=time.time() + 200 * 24 * 3600)
    (tmp_path / "plaud_token.json").write_text(json.dumps({
        "access_token": cached_token,
        "expires_at": time.time() + 200 * 24 * 3600,
    }))

    def no_post(*args, **kwargs):
        raise AssertionError("minted despite a valid cached token")

    import requests

    monkeypatch.setattr(requests, "post", no_post)
    backend = _creds_backend(tmp_path)
    assert_that(backend._resolve_token(), equal_to(cached_token))


@pytest.mark.smoke
def test_near_expiry_cached_token_is_reminted(monkeypatch, tmp_path):
    (tmp_path / "plaud_token.json").write_text(json.dumps({
        "access_token": _fake_jwt(exp=time.time() + 24 * 3600),
        "expires_at": time.time() + 24 * 3600,  # inside the 30-day buffer
    }))
    fresh = _fake_jwt(exp=time.time() + 300 * 24 * 3600)

    import requests

    monkeypatch.setattr(requests, "post", lambda *a, **k: _AuthResponse(
        {"status": 0, "access_token": fresh}))
    backend = _creds_backend(tmp_path)
    assert_that(backend._resolve_token(), equal_to(fresh))


@pytest.mark.smoke
def test_expired_envelope_mints_and_retries_once(monkeypatch, tmp_path):
    """A -419 'token expired' answer mid-listing mints a fresh token and the
    request is retried with the new bearer."""
    fresh = _fake_jwt(exp=time.time() + 300 * 24 * 3600)
    bodies = iter([
        {"status": -419, "msg": "workspace token expired"},
        {"status": 0, "data_file_list": [{"file_id": "r1", "filename": "Memo"}]},
    ])
    backend = _creds_backend(tmp_path, token="stale-manual-token")
    monkeypatch.setattr(backend, "_raw_get", lambda path, **p: next(bodies))

    import requests

    monkeypatch.setattr(requests, "post", lambda *a, **k: _AuthResponse(
        {"status": 0, "access_token": fresh}))

    recs = backend.list_recordings()

    assert_that(len(recs), equal_to(1))
    assert_that(recs[0].id, equal_to("r1"))
    cached = json.loads((tmp_path / "plaud_token.json").read_text())
    assert_that(cached["access_token"], equal_to(fresh))


@pytest.mark.smoke
def test_mint_failure_falls_back_to_manual_token(monkeypatch, tmp_path):
    import requests

    monkeypatch.setattr(requests, "post", lambda *a, **k: _AuthResponse(
        {"status": -1, "msg": "invalid credentials"}))
    backend = _creds_backend(tmp_path, token="manual-token-still-alive")
    assert_that(backend._resolve_token(), equal_to("manual-token-still-alive"))


@pytest.mark.smoke
def test_no_credentials_uses_manual_token(tmp_path):
    backend = PlaudCloudBackend(token="manual-only",
                                token_cache=str(tmp_path / "plaud_token.json"))
    assert_that(backend.auth_mode, equal_to("manual-token"))
    assert_that(backend._resolve_token(), equal_to("manual-only"))


@pytest.mark.smoke
def test_corrupt_cache_triggers_remint(monkeypatch, tmp_path):
    (tmp_path / "plaud_token.json").write_text("{not json")
    fresh = _fake_jwt(exp=time.time() + 300 * 24 * 3600)

    import requests

    monkeypatch.setattr(requests, "post", lambda *a, **k: _AuthResponse(
        {"status": 0, "access_token": fresh}))
    backend = _creds_backend(tmp_path)
    assert_that(backend._resolve_token(), equal_to(fresh))


@pytest.mark.sanity
@pytest.mark.skipif(not os.environ.get("PLAUD_TOKEN"), reason="PLAUD_TOKEN not set")
def test_cloud_backend_lists_live():
    backend = PlaudCloudBackend(token=os.environ["PLAUD_TOKEN"])
    recs = backend.list_recordings()
    assert_that(recs, instance_of(list))
