from types import SimpleNamespace

import pytest

from apps.looki.references.adapter import (
    LookiAdapter,
    normalize_moment,
    sanitize_file_payload,
)
from apps.looki.references.dto.moment import DtoLookiMoment
from apps.looki.references.web.base_api_service import BaseApiServiceLooki


class _FakeService:
    def __init__(self, payloads=None):
        self.payloads = payloads or {}
        self.days = []

    def list_moments(self, on_date):
        self.days.append(on_date)
        return self.payloads.get(on_date, {"data": {"items": []}})


def _config(api_key="test"):
    return SimpleNamespace(app_data={"api_key": api_key})


@pytest.mark.smoke
def test_status_is_local_and_does_not_call_api():
    service = _FakeService()
    adapter = LookiAdapter(_config(), service=service)

    assert adapter.status == {"ready": True, "backend": "looki-open-api"}
    assert service.days == []


@pytest.mark.smoke
@pytest.mark.parametrize("api_key", ["", None, "${LOOKI_API_KEY}"])
def test_status_not_ready_for_missing_or_unresolved_key(api_key):
    assert LookiAdapter(_config(api_key), service=_FakeService()).status["ready"] is False


@pytest.mark.smoke
def test_list_moments_normalizes_envelopes_dates_and_privacy_fields():
    service = _FakeService({
        "2026-07-18": {"data": {"items": [{
            "id": "m-1",
            "title": "Lunch",
            "description": "Shared lunch with teammates",
            "start_time": "2026-07-18T12:00:00+08:00",
            "location": {"name": "Tanjong Pagar", "latitude": 1.2, "longitude": 103.8},
            "tags": ["food", "team", "https://signed.example/x?token=secret", "1.23, 103.45"],
        }]}},
        "2026-07-19": {"moments": [{
            "moment_id": "m-2",
            "content": "Walked through the park",
            "created_at": "2026-07-19T08:30:00+08:00",
        }]},
    })
    adapter = LookiAdapter(_config(), service=service)

    moments = adapter.list_moments(
        since="2026-07-18", until="2026-07-19", max_moments=10
    )

    assert service.days == ["2026-07-18", "2026-07-19"]
    assert [m.id for m in moments] == ["m-1", "m-2"]
    assert moments[0].location_label == "Tanjong Pagar"
    assert moments[0].generated_text == "Shared lunch with teammates"
    assert moments[0].tags == ("food", "team")
    assert moments[1].generated_text == "Walked through the park"
    safe = moments[0].to_safe_dict()
    assert "latitude" not in str(safe).lower()
    assert "longitude" not in str(safe).lower()


@pytest.mark.smoke
def test_list_moments_deduplicates_and_honors_cap():
    duplicate = {"id": "same", "title": "A", "start_time": "2026-07-18T01:00:00+08:00"}
    service = _FakeService({
        "2026-07-18": [duplicate, {"id": "two", "title": "B"}],
        "2026-07-19": {"data": [duplicate, {"id": "three", "title": "C"}]},
    })
    adapter = LookiAdapter(_config(), service=service)

    moments = adapter.list_moments(
        since="2026-07-18", until="2026-07-19", max_moments=2
    )

    assert [m.id for m in moments] == ["same", "two"]
    assert service.days == ["2026-07-18"]


def test_list_moments_rejects_unbounded_empty_date_range():
    adapter = LookiAdapter(_config(), service=_FakeService())

    with pytest.raises(ValueError, match="31-day safety cap"):
        adapter.list_moments(since="2026-01-01", until="2026-07-19")


def test_api_key_is_header_only():
    config = SimpleNamespace(
        app_id="looki",
        client="rest",
        parameters={"base_url": "https://example.test/", "timeout": 1},
        app_data={"api_key": "unit-test-key"},
    )
    service = BaseApiServiceLooki(config)

    assert service._request._header["X-API-Key"] == "unit-test-key"
    assert "unit-test-key" not in service._client.base_url
    assert service._request._query_strings == {}


@pytest.mark.smoke
def test_file_payload_hides_urls_coordinates_and_unknown_fields_by_default():
    payload = {
        "files": [{
            "id": "file-1",
            "temporary_url": "https://signed.example/video.mp4?credential=secret",
            "media_url": "https://signed.example/video.mp4?signature=secret",
            "thumbnail_url": "https://signed.example/thumb.jpg",
            "media_type": "VIDEO",
            "duration_ms": 10031,
            "size": 123,
            "latitude": 1.2,
            "longitude": 103.8,
            "location": {"name": "office"},
        }],
    }

    safe = sanitize_file_payload(payload)

    assert safe == {"files": [{
        "id": "file-1",
        "media_type": "VIDEO",
        "duration_ms": 10031,
        "size": 123,
    }]}
    assert "signed.example" not in str(safe)
    assert "latitude" not in str(safe)


def test_file_payload_scrubs_urls_from_allowlisted_string_values():
    safe = sanitize_file_payload({
        "files": [{
            "id": "file-1",
            "filename": "download=https://signed.example/private.mp4?token=secret",
            "name": "[preview](https://signed.example/preview.jpg)",
            "mime_type": "video/mp4",
        }],
    })

    assert "signed.example" not in str(safe)
    assert safe["files"][0]["mime_type"] == "video/mp4"
    assert "[external-url-omitted]" in safe["files"][0]["filename"]


@pytest.mark.parametrize(
    "location",
    [
        "1.3521, 103.8198",
        "103.8198, 1.3521",
        "1.3521° N, 103.8198° E",
        "lat=1.3521; lng=103.8198",
        "longitude=103.8198; latitude=1.3521",
        "103° 49' 11\" E, 1° 21' 08\" N",
        "1°21′08″N 103°49′11″E",
    ],
)
def test_coordinate_valued_location_labels_are_omitted(location):
    assert normalize_moment({"id": "m-1", "location": location}).location_label is None


def test_ordinary_location_label_is_retained():
    moment = normalize_moment({"id": "m-1", "location": "Tanjong Pagar"})
    assert moment.location_label == "Tanjong Pagar"


@pytest.mark.parametrize("moment_id", ["bad\nid", "bad\rid", "bad\tid", " bad-id"])
def test_control_or_whitespace_moment_ids_are_invalid_not_normalized(moment_id):
    moment = normalize_moment({"id": moment_id, "uuid": "fallback-id"})

    assert moment.id is None


def test_file_payload_explicit_urls_keeps_only_named_string_url_fields():
    payload = {
        "data": {"files": [{
            "id": "file-1",
            "temporary_url": "https://signed.example/temp",
            "download_url": "https://signed.example/download",
            "url": "https://signed.example/direct",
            "future_vendor_url": "https://signed.example/unknown",
            "latitude": 1.3521,
            "longitude": 103.8198,
            "filename": "camera 103.8198, 1.3521.mp4",
            "unknown": "private",
        }]},
    }

    default = sanitize_file_payload(payload)
    explicit = sanitize_file_payload(payload, include_temporary_urls=True)

    assert default == {"data": {"files": [{"id": "file-1"}]}}
    assert explicit == {"data": {"files": [{
        "id": "file-1",
        "temporary_url": "https://signed.example/temp",
        "download_url": "https://signed.example/download",
        "url": "https://signed.example/direct",
    }]}}
    assert "future_vendor_url" not in str(explicit)
    assert "103.8198" not in str(explicit)


def test_safe_dict_defensively_sanitizes_every_free_text_path():
    safe = DtoLookiMoment(
        id="m-1",
        title="Watch [clip](https://signed.example/title)",
        generated_text="GeoJSON point 103.8198, 1.3521",
        location_label="longitude=103.8198; latitude=1.3521",
        tags=("team", "1°21′08″N 103°49′11″E", "url=https://signed.example/tag"),
    ).to_safe_dict()

    assert "signed.example" not in str(safe)
    assert "103.8198" not in str(safe)
    assert "1°21" not in str(safe)
    assert safe["title"] == "Watch [clip]([external-url-omitted]"
    assert safe["generated_text"] is None
    assert safe["location_label"] is None
    assert safe["tags"] == ["team"]


def test_non_coordinate_prose_is_retained():
    moment = normalize_moment({
        "id": "m-1",
        "title": "Release 1.2 is ready",
        "description": "Met 2 teammates at Tanjong Pagar",
        "tags": ["version-1.2", "team"],
    })

    assert moment.title == "Release 1.2 is ready"
    assert moment.generated_text == "Met 2 teammates at Tanjong Pagar"
    assert moment.tags == ("version-1.2", "team")
