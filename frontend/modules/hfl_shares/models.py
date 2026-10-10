"""Domain models for saved share recipes and immutable snapshots."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace, field
from datetime import datetime, timezone
from typing import Any


AUTH_MODES = ("pin", "email_otp", "manual", "qr")
ALL_SOURCES = "__all__"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_csv(value: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            item.strip()
            for item in (value or "").replace("\n", ",").split(",")
            if item.strip()
        )
    )


@dataclass(frozen=True)
class ShareConfiguration:
    id: str
    name: str
    recipient: str = ""
    description: str = ""
    sources: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    date_from: str = ""
    date_to: str = ""
    topic: str = ""
    selected_entry_ids: tuple[str, ...] = ()
    context_prompt: str = ""
    auth_mode: str = "pin"
    allowed_email: str = ""
    references_enabled: bool = False
    include_secrets: bool = False
    disabled_reference_ids: tuple[str, ...] = ()
    live_updates: bool = False
    ttl_seconds: int = 3600
    no_expiry: bool = False
    device_limit: int = 1
    single_use: bool = False
    browser_redemption_limit: int = 5
    created_at: str = ""
    updated_at: str = ""
    date_field: str = "entry"
    corpus_scope: str = ""
    from_days: int = 0
    activity: dict[str, Any] = field(default_factory=dict)
    entity_id: str = ""
    entity_name: str = ""
    entity_kind: str = ""
    entity_template: bool = False
    entity_ids: tuple[str, ...] = ()
    entities: tuple[dict[str, str], ...] = ()
    persona: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.entity_ids, (tuple, list)) or any(not isinstance(value, str) or not value.strip() or len(value) > 500 for value in self.entity_ids):
            raise ValueError('Entity selections must contain valid entity IDs.')
        object.__setattr__(self, 'entity_ids', tuple(dict.fromkeys(self.entity_ids)))
        if type(self.from_days) is not int or self.from_days not in {0, 15, 30, 90}:
            raise ValueError("From days must be None, 15, 30, or 90.")
        if self.activity:
            from modules.hfl_shares.activity_models import ActivitySelection
            ActivitySelection.model_validate(self.activity)
        if self.corpus_scope:
            from modules.hfl_corpus.view_scope import parse_scope
            parse_scope(self.corpus_scope)
        if self.date_field not in {"entry", "created", "updated"}:
            raise ValueError("Invalid date type.")
        if not self.name.strip():
            raise ValueError("Configuration name is required.")
        if len(self.name) > 120:
            raise ValueError("Configuration name must be 120 characters or fewer.")
        # Legacy saved recipes have no recipient. They may still be loaded so
        # the owner can supply one, but every new form submission validates it.
        if any(len(value) > 500 for value in (self.entity_id, self.entity_name, self.entity_kind)):
            raise ValueError("Entity values must be 500 characters or fewer.")
        if not self.recipient.strip() and not self.id and not self.entity_template and not self.entity_id and not self.entity_ids:
            raise ValueError("Recipient is required.")
        if len(self.recipient) > 500:
            raise ValueError("Recipient must be 500 characters or fewer.")
        if len(self.description) > 1000:
            raise ValueError("Description must be 1000 characters or fewer.")
        if not self.sources:
            raise ValueError("At least one source is required.")
        if ALL_SOURCES in self.sources and self.sources != (ALL_SOURCES,):
            raise ValueError("All sources cannot be combined with individual sources.")
        if len(self.sources) > 50 or any(
            not source.strip() or len(source) > 100 for source in self.sources
        ):
            raise ValueError("Select no more than 50 valid sources.")
        if len(self.tags) > 50 or any(len(tag) > 100 for tag in self.tags):
            raise ValueError("Use no more than 50 tags of 100 characters each.")
        if len(self.topic) > 500:
            raise ValueError("Topic must be 500 characters or fewer.")
        if len(self.context_prompt) > 4_000:
            raise ValueError("Context prompt must be 4000 characters or fewer.")
        if self.auth_mode not in AUTH_MODES:
            raise ValueError("Unsupported authentication mode.")
        if self.auth_mode == "email_otp" and not self.allowed_email.strip():
            raise ValueError("Email OTP mode requires an allowed email address.")
        if len(self.allowed_email) > 320 or (
            self.auth_mode == "email_otp"
            and (
                "@" not in self.allowed_email
                or self.allowed_email.startswith("@")
                or self.allowed_email.endswith("@")
            )
        ):
            raise ValueError("Email OTP mode requires a valid email address.")
        if self.date_from and self.date_to:
            try:
                if datetime.fromisoformat(self.date_from) > datetime.fromisoformat(
                    self.date_to
                ):
                    raise ValueError("The start date must not follow the end date.")
            except ValueError as exc:
                if str(exc) == "The start date must not follow the end date.":
                    raise
                raise ValueError("Share dates must use YYYY-MM-DD format.") from exc
        if not self.no_expiry and not 300 <= int(self.ttl_seconds) <= 31_536_000:
            raise ValueError("Duration must be between five minutes and 365 days.")
        if type(self.browser_redemption_limit) is not int or not 0 <= self.browser_redemption_limit <= 1000:
            raise ValueError("Maximum redemptions must be between zero and 1000.")
        if not 1 <= int(self.device_limit) <= 20:
            raise ValueError("Session limit must be between one and twenty.")

    def saved(self, *, configuration_id: str, now: str) -> "ShareConfiguration":
        return replace(
            self,
            id=configuration_id,
            created_at=self.created_at or now,
            updated_at=now,
        )

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SnapshotReference:
    id: str
    label: str
    kind: str
    target: str
    enabled: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "kind": self.kind}


@dataclass(frozen=True)
class SnapshotEntry:
    id: str
    citation: str
    relative_path: str
    anchor: str
    header: str
    moment: str
    what_happened: str
    source: str
    tags: tuple[str, ...]
    text: str
    references: tuple[SnapshotReference, ...] = ()

    def to_record(self) -> dict[str, Any]:
        data = asdict(self)
        data["tags"] = list(self.tags)
        data["references"] = [asdict(item) for item in self.references]
        return data

    @classmethod
    def from_record(cls, value: dict[str, Any]) -> "SnapshotEntry":
        return cls(
            id=str(value.get("id") or ""),
            citation=str(value.get("citation") or ""),
            relative_path=str(value.get("relative_path") or ""),
            anchor=str(value.get("anchor") or ""),
            header=str(value.get("header") or ""),
            moment=str(value.get("moment") or ""),
            what_happened=str(value.get("what_happened") or ""),
            source=str(value.get("source") or ""),
            tags=tuple(str(item) for item in value.get("tags") or []),
            text=str(value.get("text") or ""),
            references=tuple(
                SnapshotReference(**item) for item in value.get("references") or []
            ),
        )


@dataclass(frozen=True)
class ScopeSnapshot:
    entries: tuple[SnapshotEntry, ...]
    created_at: str
    sources: tuple[str, ...]
    filters: dict[str, Any]
    source_counts: dict[str, int]
    tag_counts: dict[str, int]
    earliest: str = ""
    latest: str = ""
    estimated_chars: int = 0
    available_references: int = 0
    enabled_reference_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    context_prompt: str = ""
    recipient: str = ""
    activity: dict[str, Any] = field(default_factory=dict)
    activity_entries: tuple[SnapshotEntry, ...] = ()

    persona_entries: tuple[SnapshotEntry, ...] = ()
    opportunity: dict[str, str] = field(default_factory=dict)

    @property
    def all_entries(self):
        return self.entries + self.activity_entries + self.persona_entries

    def to_record(self) -> dict[str, Any]:
        return {
            "entries": [entry.to_record() for entry in self.entries],
            "created_at": self.created_at,
            "sources": list(self.sources),
            "filters": self.filters,
            "source_counts": self.source_counts,
            "tag_counts": self.tag_counts,
            "earliest": self.earliest,
            "latest": self.latest,
            "estimated_chars": self.estimated_chars,
            "available_references": self.available_references,
            "enabled_reference_ids": list(self.enabled_reference_ids),
            "warnings": list(self.warnings),
            "context_prompt": self.context_prompt,
            "recipient": self.recipient,
            "activity": self.activity,
            "activity_entries": [entry.to_record() for entry in self.activity_entries],
            "persona_entries": [entry.to_record() for entry in self.persona_entries],
            "opportunity": self.opportunity,
        }

    @classmethod
    def from_record(cls, value: dict[str, Any]) -> "ScopeSnapshot":
        return cls(
            entries=tuple(
                SnapshotEntry.from_record(item)
                for item in value.get("entries") or []
            ),
            created_at=str(value.get("created_at") or ""),
            sources=tuple(str(item) for item in value.get("sources") or []),
            filters=dict(value.get("filters") or {}),
            source_counts={
                str(key): int(count)
                for key, count in (value.get("source_counts") or {}).items()
            },
            tag_counts={
                str(key): int(count)
                for key, count in (value.get("tag_counts") or {}).items()
            },
            earliest=str(value.get("earliest") or ""),
            latest=str(value.get("latest") or ""),
            estimated_chars=int(value.get("estimated_chars") or 0),
            available_references=int(value.get("available_references") or 0),
            enabled_reference_ids=tuple(
                str(item) for item in value.get("enabled_reference_ids") or []
            ),
            warnings=tuple(str(item) for item in value.get("warnings") or []),
            context_prompt=str(value.get("context_prompt") or ""),
            recipient=str(value.get("recipient") or ""),
            activity=dict(value.get("activity") or {}),
            activity_entries=tuple(SnapshotEntry.from_record(item) for item in value.get("activity_entries") or []),
            persona_entries=tuple(SnapshotEntry.from_record(item) for item in value.get("persona_entries") or []),
            opportunity=dict(value.get("opportunity") or {}),
        )


@dataclass(frozen=True)
class ShareGrant:
    id: str
    configuration_id: str
    name: str
    auth_mode: str
    allowed_email: str
    snapshot: ScopeSnapshot
    created_at: str
    expires_at: str
    status: str
    single_use: bool
    device_limit: int
    no_expiry: bool = False
    instant: bool = False
    live_updates: bool = False
    live_configuration: ShareConfiguration | None = None
    redeemed_at: str = ""
    revoked_at: str = ""
    pin_failures: int = 0
    browser_redemption_limit: int = 0
    refresh_error: str = ""
    redemption_expires_at: str = ""
    redemption_session_seconds: int = 0

    @property
    def expired(self) -> bool:
        if self.no_expiry:
            return False
        try:
            return datetime.fromisoformat(self.expires_at) <= utc_now()
        except ValueError:
            return True

    @property
    def available(self) -> bool:
        return self.status == "active" and not self.expired


@dataclass(frozen=True)
class ShareGrantSummary:
    """Snapshot-free projection used by the owner share listing."""

    id: str
    configuration_id: str
    name: str
    auth_mode: str
    allowed_email: str
    created_at: str
    expires_at: str
    status: str
    single_use: bool
    device_limit: int
    entry_count: int
    no_expiry: bool = False
    instant: bool = False
    live_updates: bool = False
    redeemed_at: str = ""
    revoked_at: str = ""
    pin_failures: int = 0
    browser_redemption_limit: int = 0

    @property
    def expired(self) -> bool:
        if self.no_expiry:
            return False
        try:
            return datetime.fromisoformat(self.expires_at) <= utc_now()
        except ValueError:
            return True

    @property
    def available(self) -> bool:
        return self.status == "active" and not self.expired


@dataclass(frozen=True)
class ChatMessage:
    id: str
    session_id: str
    share_id: str
    role: str
    content: str
    created_at: str
