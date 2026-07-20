from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional, Protocol

from apps.looki.references.dto.moment import (
    DtoLookiMoment,
    contains_precise_coordinates,
    safe_moment_text,
    scrub_url_string,
    valid_moment_id,
)
from apps.looki.references.web.api.looki import ApiServiceLooki


_ITEM_KEYS = ("items", "moments", "records", "results", "list")
def _contains_precise_coordinates(value: str) -> bool:
    return contains_precise_coordinates(value)


def _scrub_url_string(value: str) -> str:
    return scrub_url_string(value)


def _resolved_secret(value: Any) -> str:
    text = str(value or "").strip()
    return "" if not text or "${" in text else text


def extract_items(payload: Any) -> list[dict]:
    """Tolerate the envelope variants observed across Looki client examples.

    Official OpenAPI/schema documentation is not public, so response handling is
    deliberately conservative. Only dictionaries representing list items are
    returned; unknown shapes become a clean empty list.
    """
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    candidates: list[Any] = [payload]
    for key in ("data", "result"):
        nested = payload.get(key)
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
        if isinstance(nested, dict):
            candidates.insert(0, nested)

    for container in candidates:
        for key in _ITEM_KEYS:
            items = container.get(key) if isinstance(container, dict) else None
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
    return []


def _first_text(raw: dict, keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        value = raw.get(key)
        if value is not None and not isinstance(value, (dict, list)):
            text = str(value).strip()
            if text:
                return text
    return None


def _location_label(value: Any) -> Optional[str]:
    if isinstance(value, str):
        label = value.strip()
        return safe_moment_text(label)
    if isinstance(value, dict):
        # Coordinates are intentionally ignored. HFL gets only a human label.
        label = _first_text(value, ("name", "label", "place", "city", "address"))
        return safe_moment_text(label)
    return None


def _tags(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set)):
        return ()
    cleaned: list[str] = []
    for item in value:
        if isinstance(item, dict):
            text = _first_text(item, ("name", "label", "value"))
        else:
            text = str(item).strip() if item is not None else ""
        if (
            text
            and safe_moment_text(text) == text
            and text not in cleaned
        ):
            cleaned.append(text[:80])
    return tuple(cleaned[:20])


def normalize_moment(raw: dict) -> DtoLookiMoment:
    """Map one vendor payload to metadata safe for downstream persistence."""
    location = raw.get("location")
    if location is None:
        location = raw.get("place")
    tags = raw.get("tags")
    if tags is None:
        tags = raw.get("labels") or raw.get("categories")
    return DtoLookiMoment(
        id=valid_moment_id(
            next((raw[key] for key in ("id", "moment_id", "uuid") if key in raw), None)
        ),
        title=safe_moment_text(_first_text(raw, ("title", "name", "headline"))),
        generated_text=safe_moment_text(
            _first_text(raw, ("description", "content", "summary", "caption"))
        ),
        started_at=_first_text(raw, ("start_time", "started_at", "recorded_at", "created_at")),
        ended_at=_first_text(raw, ("end_time", "ended_at")),
        timezone=_first_text(raw, ("tz", "timezone", "time_zone")),
        location_label=_location_label(location),
        tags=_tags(tags),
    )


_SAFE_FILE_FIELDS = {
    "id", "file_id", "name", "filename", "type", "mime_type", "media_type",
    "content_type", "size", "size_bytes", "duration", "duration_ms", "duration_seconds",
    "width", "height", "created_at", "updated_at", "checksum", "sha256",
}
_FILE_ENVELOPE_KEYS = {"data", "items", "files", "result"}
_TEMPORARY_URL_FIELDS = {
    "temporary_url", "presigned_url", "signed_url", "download_url", "media_url",
    "thumbnail_url", "url",
}


def sanitize_file_payload(payload: Any, *, include_temporary_urls: bool = False) -> Any:
    """Return inert file metadata only; fail closed on unknown API fields.

    The live schema is not publicly documented, so a denylist would leak any
    newly named signed-URL or coordinate field. Only known primitive metadata
    and known response envelopes survive.
    """
    if isinstance(payload, list):
        return [
            sanitize_file_payload(item, include_temporary_urls=include_temporary_urls)
            for item in payload
        ]
    if not isinstance(payload, dict):
        if isinstance(payload, str):
            return None if _contains_precise_coordinates(payload) else _scrub_url_string(payload)
        return payload if isinstance(payload, (int, float, bool)) or payload is None else None
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        key_l = str(key).lower()
        if key_l in _FILE_ENVELOPE_KEYS:
            safe[key] = sanitize_file_payload(
                value, include_temporary_urls=include_temporary_urls
            )
        elif (
            include_temporary_urls
            and key_l in _TEMPORARY_URL_FIELDS
            and isinstance(value, str)
            and not _contains_precise_coordinates(value)
        ):
            safe[key] = value
        elif key_l in _SAFE_FILE_FIELDS and (
            isinstance(value, (str, int, float, bool)) or value is None
        ):
            if not isinstance(value, str) or not _contains_precise_coordinates(value):
                safe[key] = _scrub_url_string(value) if isinstance(value, str) else value
    return safe


def _parse_day(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()


class LookiService(Protocol):
    def list_moments(self, on_date: str) -> Any: ...
    def get_moment(self, moment_id: str) -> dict: ...
    def search_moments(self, query: str, **kwargs) -> Any: ...
    def list_moment_files(self, moment_id: str, **kwargs) -> Any: ...


class LookiAdapter:
    """Metadata-first facade around the Looki Open API."""

    def __init__(self, config, *, service: Optional[LookiService] = None):
        self.config = config
        self._service = service
        self._api_key = _resolved_secret((config.app_data or {}).get("api_key"))

    @property
    def status(self) -> dict:
        ready = bool(self._api_key)
        return {"ready": ready, "backend": "looki-open-api" if ready else None}

    @property
    def service(self) -> ApiServiceLooki:
        if not self._api_key:
            raise RuntimeError("LOOKI_API_KEY is not configured")
        if self._service is None:
            self._service = ApiServiceLooki(self.config, api_key=self._api_key)
        return self._service

    def list_moments(
        self,
        *,
        since: str | date,
        until: str | date,
        max_moments: int = 200,
        max_days: int = 31,
    ) -> list[DtoLookiMoment]:
        start, end = _parse_day(since), _parse_day(until)
        if start > end:
            raise ValueError("since must be on or before until")
        span_days = (end - start).days + 1
        safety_cap = max(1, min(int(max_days), 31))
        if span_days > safety_cap:
            raise ValueError(f"Looki date window exceeds the {safety_cap}-day safety cap")
        limit = max(1, min(int(max_moments), 1000))
        moments: list[DtoLookiMoment] = []
        seen: set[str] = set()
        current = start
        while current <= end and len(moments) < limit:
            payload = self.service.list_moments(on_date=current.isoformat())
            for raw in extract_items(payload):
                moment = normalize_moment(raw)
                dedupe_key = moment.id or repr(moment.to_safe_dict())
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                moments.append(moment)
                if len(moments) >= limit:
                    break
            current += timedelta(days=1)
        return moments

    def get_moment(self, moment_id: str) -> dict:
        return self.service.get_moment(moment_id)

    def search_moments(self, query: str, **kwargs) -> list[DtoLookiMoment]:
        payload = self.service.search_moments(query, **kwargs)
        return [normalize_moment(item) for item in extract_items(payload)]

    def list_moment_files(
        self, moment_id: str, *, include_temporary_urls: bool = False, **kwargs
    ) -> Any:
        payload = self.service.list_moment_files(moment_id, **kwargs)
        return sanitize_file_payload(
            payload, include_temporary_urls=include_temporary_urls
        )


def build_adapter(config) -> LookiAdapter:
    return LookiAdapter(config)
