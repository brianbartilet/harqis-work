"""Versioned contracts for the portable Second Brain data plane."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable


ALLOWED_CLIENTS = frozenset({"web", "telegram", "rainmeter", "cli"})
SCHEMA_VERSION = 2
MODE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,47}$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime | None = None) -> str:
    return (value or utc_now()).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_id(prefix: str, *parts: object) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(raw).hexdigest()[:24]}"


def normalize_modes(modes: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(str(mode).strip().casefold() for mode in modes if str(mode).strip()))
    invalid = {mode for mode in normalized if not MODE_ID_PATTERN.fullmatch(mode)}
    if invalid:
        raise ValueError(f"unsupported Second Brain mode(s): {', '.join(sorted(invalid))}")
    return normalized


@dataclass(frozen=True)
class ModeDefinition:
    mode_id: str
    name: str
    color: str = "#38bdf8"
    order: int = 0
    enabled: bool = True
    archived: bool = False
    keywords: tuple[str, ...] = ()
    calendar_categories: tuple[str, ...] = ()
    operation_ids: tuple[str, ...] = ()
    refresh_minutes: int = 15
    client_eligibility: tuple[str, ...] = ("web", "telegram", "rainmeter", "cli")
    fallback_windows: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        mode_id = self.mode_id.strip().casefold()
        if not MODE_ID_PATTERN.fullmatch(mode_id):
            raise ValueError("mode id must be a lowercase slug")
        if not self.name.strip():
            raise ValueError("mode name is required")
        color = self.color.strip().lower()
        if not re.fullmatch(r"#[0-9a-f]{6}", color):
            raise ValueError("mode color must be a six-digit hex value")
        clients = tuple(dict.fromkeys(str(value).strip().casefold() for value in self.client_eligibility))
        if set(clients) - ALLOWED_CLIENTS:
            raise ValueError("mode has unsupported clients")
        object.__setattr__(self, "mode_id", mode_id)
        object.__setattr__(self, "name", self.name.strip()[:80])
        object.__setattr__(self, "color", color)
        object.__setattr__(self, "order", max(0, int(self.order)))
        object.__setattr__(self, "keywords", tuple(dict.fromkeys(k.strip().casefold() for k in self.keywords if k.strip())))
        object.__setattr__(self, "calendar_categories", tuple(dict.fromkeys(str(v).strip() for v in self.calendar_categories if str(v).strip())))
        object.__setattr__(self, "operation_ids", tuple(dict.fromkeys(str(v).strip() for v in self.operation_ids if str(v).strip())))
        object.__setattr__(self, "refresh_minutes", max(1, min(1440, int(self.refresh_minutes))))
        object.__setattr__(self, "client_eligibility", clients)
        windows = []
        for value in self.fallback_windows:
            start, end = str(value.get("start", "")), str(value.get("end", ""))
            if not (re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", start) and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", end)):
                raise ValueError("fallback windows require valid HH:MM start and end")
            days = tuple(sorted({int(day) for day in value.get("days", range(7))}))
            if not days or any(day < 0 or day > 6 for day in days):
                raise ValueError("fallback window days must be between 0 and 6")
            windows.append({"start": start, "end": end, "days": list(days)})
        object.__setattr__(self, "fallback_windows", tuple(windows))

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("keywords", "calendar_categories", "operation_ids", "client_eligibility", "fallback_windows"):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True)
class ContextEvent:
    source: str
    event_type: str
    payload: dict[str, Any]
    observed_at: str = field(default_factory=isoformat)
    received_at: str = field(default_factory=isoformat)
    sensitivity: str = "internal"
    retention_class: str = "structured-30d"
    source_ref: str = ""
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    causation_id: str = ""
    dedup_key: str = ""
    expires_at: str = ""
    consent_scope: str = "owner"
    event_id: str = ""
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        source = self.source.strip().casefold()
        event_type = self.event_type.strip().casefold().replace(" ", "_")
        if not source or not event_type:
            raise ValueError("context events require source and event_type")
        encoded = json.dumps(self.payload, ensure_ascii=False, default=str).encode("utf-8")
        if len(encoded) > 32_768:
            raise ValueError("context payload exceeds 32 KiB")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "event_type", event_type)
        if not self.event_id:
            object.__setattr__(
                self,
                "event_id",
                stable_id("ctx", source, event_type, self.dedup_key or self.observed_at, self.payload),
            )

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModeDecision:
    effective_modes: tuple[str, ...]
    detected_modes: tuple[str, ...]
    manual_modes: tuple[str, ...] = ()
    confidence: float = 0.0
    reason_codes: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    resolver_version: str = "deterministic-v1"
    valid_until: str = ""
    agent_profile: str = ""
    skill_name: str = ""
    skill_hash: str = ""
    model: str = ""
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    evaluated_at: str = field(default_factory=isoformat)
    decision_id: str = ""
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        effective = normalize_modes(self.effective_modes)
        detected = normalize_modes(self.detected_modes)
        manual = normalize_modes(self.manual_modes)
        object.__setattr__(self, "effective_modes", effective)
        object.__setattr__(self, "detected_modes", detected)
        object.__setattr__(self, "manual_modes", manual)
        object.__setattr__(self, "confidence", max(0.0, min(1.0, float(self.confidence))))
        if not self.decision_id:
            object.__setattr__(
                self,
                "decision_id",
                stable_id("mode", self.evaluated_at, effective, self.correlation_id),
            )

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("effective_modes", "detected_modes", "manual_modes", "reason_codes", "evidence_refs"):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True)
class FeedItem:
    logical_key: str
    category: str
    kind: str
    title: str
    summary: str
    details: str = ""
    priority: int = 50
    confidence: float = 1.0
    urgency: int = 0
    status: str = "fresh"
    source_refs: tuple[str, ...] = ()
    generated_at: str = field(default_factory=isoformat)
    source_at: str = ""
    fresh_until: str = ""
    expires_at: str = ""
    sensitivity: str = "internal"
    allowed_clients: tuple[str, ...] = ("web",)
    links: dict[str, str] = field(default_factory=dict)
    actions: tuple[dict[str, Any], ...] = ()
    reason_codes: tuple[str, ...] = ()
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str = ""
    operation_id: str = ""
    item_id: str = ""
    revision: int = 0
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        category = self.category.strip().casefold()
        if not MODE_ID_PATTERN.fullmatch(category):
            raise ValueError(f"unsupported feed category: {category}")
        if not self.logical_key.strip() or not self.title.strip():
            raise ValueError("feed items require logical_key and title")
        clients = tuple(dict.fromkeys(str(client).strip().casefold() for client in self.allowed_clients))
        invalid = set(clients) - ALLOWED_CLIENTS
        if invalid:
            raise ValueError(f"unsupported feed client(s): {', '.join(sorted(invalid))}")
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "allowed_clients", clients)
        object.__setattr__(self, "priority", max(0, min(100, int(self.priority))))
        object.__setattr__(self, "confidence", max(0.0, min(1.0, float(self.confidence))))
        if not self.item_id:
            object.__setattr__(self, "item_id", stable_id("feed", self.logical_key))

    def content_hash(self) -> str:
        material = {
            "category": self.category,
            "kind": self.kind,
            "title": self.title,
            "summary": self.summary,
            "details": self.details,
            "priority": self.priority,
            "confidence": self.confidence,
            "urgency": self.urgency,
            "status": self.status,
            "source_refs": self.source_refs,
            "source_at": self.source_at,
            "sensitivity": self.sensitivity,
            "allowed_clients": self.allowed_clients,
            "links": self.links,
            "actions": self.actions,
            "reason_codes": self.reason_codes,
            "operation_id": self.operation_id,
        }
        encoded = json.dumps(material, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("source_refs", "allowed_clients", "actions", "reason_codes"):
            payload[key] = list(payload[key])
        payload["content_hash"] = self.content_hash()
        return payload
