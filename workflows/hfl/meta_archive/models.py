"""Canonical, portable records produced from Facebook and Instagram exports."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def stable_hash(*parts: object) -> str:
    value = json.dumps(parts, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MetaAttachment:
    kind: str
    path: str = ""
    uri: str = ""
    title: str = ""
    media_id: str = ""
    reference: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MetaAttachment":
        names = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{key: str(val or "") for key, val in value.items() if key in names})


@dataclass(frozen=True)
class MetaEvent:
    platform: str
    thread_id: str
    thread_title: str
    participants: tuple[str, ...]
    sender: str
    occurred_at_utc: datetime
    occurred_at_local: datetime
    event_type: str
    content: str = ""
    attachments: tuple[MetaAttachment, ...] = field(default_factory=tuple)
    references: tuple[str, ...] = field(default_factory=tuple)
    event_id: str = ""

    def __post_init__(self) -> None:
        if not self.event_id:
            attachment_ids = tuple(a.media_id or a.uri or a.path for a in self.attachments)
            object.__setattr__(self, "event_id", stable_hash(
                self.platform, self.thread_id, self.sender,
                self.occurred_at_utc.isoformat(), self.event_type,
                " ".join(self.content.split()), attachment_ids,
            ))

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["occurred_at_utc"] = self.occurred_at_utc.isoformat()
        result["occurred_at_local"] = self.occurred_at_local.isoformat()
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MetaEvent":
        data = dict(value)
        data["participants"] = tuple(str(v) for v in data.get("participants") or [])
        data["references"] = tuple(str(v) for v in data.get("references") or [])
        data["attachments"] = tuple(
            MetaAttachment.from_dict(v) for v in data.get("attachments") or []
        )
        data["occurred_at_utc"] = datetime.fromisoformat(data["occurred_at_utc"])
        data["occurred_at_local"] = datetime.fromisoformat(data["occurred_at_local"])
        return cls(**data)


def media_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
