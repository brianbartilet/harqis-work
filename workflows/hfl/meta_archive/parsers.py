"""Best-effort parsers for Meta's Facebook JSON and Instagram HTML exports."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from workflows.hfl.meta_archive.models import MetaAttachment, MetaEvent, media_hash, stable_hash

_SINGAPORE = ZoneInfo("Asia/Singapore")
_IG_STAMP = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) "
    r"\d{2}, \d{4} \d{1,2}:\d{2} (?:am|pm)\b", re.I,
)
_MEDIA_KEYS = {
    "photos": "image", "videos": "video", "audio_files": "audio",
    "gifs": "gif", "files": "file", "sticker": "sticker", "share": "share",
}


def _text(value: Any) -> str:
    raw = str(value or "")
    try:
        return raw.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return raw


def _reference(platform: str, export_root: Path, artifact: Path) -> str:
    rel = artifact.relative_to(export_root).as_posix()
    return f"meta-archive://{platform}/{export_root.name}/{rel}"


def _attachment(platform: str, export_root: Path, source: Path, kind: str,
                raw: dict[str, Any]) -> MetaAttachment:
    uri = _text(raw.get("uri") or raw.get("url") or "")
    is_remote = uri.startswith(("http://", "https://", "mailto:"))
    candidate = export_root / Path(unquote(uri)) if uri and not is_remote else None
    if candidate and not candidate.exists():
        candidate = source.parent / unquote(uri)
    path = str(candidate.resolve()) if candidate and candidate.exists() else ""
    identity = media_hash(candidate) if candidate and candidate.is_file() else stable_hash(kind, uri)
    ref = _reference(platform, export_root, candidate) if candidate and candidate.exists() else _reference(platform, export_root, source)
    return MetaAttachment(kind=kind, path=path, uri=uri,
                          title=_text(raw.get("title") or raw.get("description") or ""),
                          media_id=identity, reference=ref)


def parse_facebook_thread(path: Path, export_root: Path,
                          tz: ZoneInfo = _SINGAPORE) -> list[MetaEvent]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    participants = tuple(_text(p.get("name")) for p in payload.get("participants") or [])
    title = _text(payload.get("title") or path.parent.name)
    thread_id = _text(payload.get("thread_path") or path.parent.name)
    events: list[MetaEvent] = []
    for message in payload.get("messages") or []:
        stamp = message.get("timestamp_ms")
        if stamp is None:
            continue
        utc = datetime.fromtimestamp(float(stamp) / 1000, tz=timezone.utc)
        attachments: list[MetaAttachment] = []
        for key, kind in _MEDIA_KEYS.items():
            values = message.get(key)
            if values is None:
                continue
            if not isinstance(values, list):
                values = [values]
            for raw in values:
                attachments.append(_attachment("facebook", export_root, path, kind,
                                               raw if isinstance(raw, dict) else {"title": raw}))
        content = _text(message.get("content") or "")
        event_type = "message" if content else (attachments[0].kind if attachments else "message")
        refs = tuple(dict.fromkeys([_reference("facebook", export_root, path), *[a.reference for a in attachments]]))
        events.append(MetaEvent(
            platform="facebook", thread_id=thread_id, thread_title=title,
            participants=participants, sender=_text(message.get("sender_name")),
            occurred_at_utc=utc, occurred_at_local=utc.astimezone(tz),
            event_type=event_type, content=content,
            attachments=tuple(attachments), references=refs,
            raw_timestamp=str(stamp),
            source_reference=_reference("facebook", export_root, path),
        ))
    return events


def _ig_attachment(platform: str, export_root: Path, source: Path, node: Any) -> list[MetaAttachment]:
    found: list[MetaAttachment] = []
    for tag in node.find_all(["img", "video", "audio", "a"]):
        uri = tag.get("src") or tag.get("href") or ""
        if not uri or uri.startswith(("http://", "https://", "mailto:")):
            continue
        suffix = Path(unquote(uri)).suffix.lower()
        kind = "video" if tag.name == "video" or suffix in {".mp4", ".mov", ".webm"} else "audio" if tag.name == "audio" or suffix in {".mp3", ".m4a", ".wav", ".ogg"} else "image" if tag.name == "img" or suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp"} else "file"
        found.append(_attachment(platform, export_root, source, kind, {"uri": uri, "title": tag.get_text(" ", strip=True)}))
    return found


def parse_instagram_html(path: Path, export_root: Path, *, thread_id: str,
                         authored: bool = False,
                         tz: ZoneInfo = _SINGAPORE) -> list[MetaEvent]:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    title = _text(soup.title.get_text(" ", strip=True) if soup.title else thread_id)
    events: list[MetaEvent] = []
    blocks = soup.select("div.pam")
    for block in blocks:
        text = block.get_text("\n", strip=True)
        match = _IG_STAMP.search(text)
        if not match:
            continue
        local = datetime.strptime(match.group(0).lower(), "%b %d, %Y %I:%M %p").replace(tzinfo=tz)
        sender_node = block.find("h2")
        sender = _text(sender_node.get_text(" ", strip=True) if sender_node else ("self" if authored else ""))
        content_node = block.select_one("div._a6-p")
        content = _text(content_node.get_text(" ", strip=True) if content_node else "")
        attachments = tuple(_ig_attachment("instagram", export_root, path, block))
        refs = tuple(dict.fromkeys([_reference("instagram", export_root, path), *[a.reference for a in attachments]]))
        events.append(MetaEvent(
            platform="instagram", thread_id=thread_id,
            thread_title="Authored posts and stories" if authored else title,
            participants=(title,) if not authored else ("self",), sender=sender,
            occurred_at_utc=local.astimezone(timezone.utc), occurred_at_local=local,
            event_type="authored-content" if authored else "message", content=content,
            attachments=attachments, references=refs,
            raw_timestamp=match.group(0),
            source_reference=_reference("instagram", export_root, path),
        ))
    return events


def _walk_post_objects(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if any(key in value for key in ("timestamp", "timestamp_ms")) and any(key in value for key in ("data", "title", "attachments")):
            yield value
        for child in value.values():
            yield from _walk_post_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_post_objects(child)


def parse_facebook_posts(path: Path, export_root: Path,
                         tz: ZoneInfo = _SINGAPORE) -> list[MetaEvent]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    events: list[MetaEvent] = []
    for raw in _walk_post_objects(payload):
        stamp = raw.get("timestamp_ms")
        utc = datetime.fromtimestamp(float(stamp) / (1000 if stamp and float(stamp) > 10_000_000_000 else 1), tz=timezone.utc) if stamp is not None else datetime.fromtimestamp(float(raw["timestamp"]), tz=timezone.utc)
        data = raw.get("data") or []
        content = "\n".join(_text(item.get("post") or item.get("comment") or item.get("text")) for item in data if isinstance(item, dict)).strip()
        attachments: list[MetaAttachment] = []
        for attachment in raw.get("attachments") or []:
            for item in (attachment.get("data") or []) if isinstance(attachment, dict) else []:
                media = item.get("media") or {}
                if media:
                    attachments.append(_attachment("facebook", export_root, path, "media", media))
        events.append(MetaEvent(
            platform="facebook", thread_id="authored-content",
            thread_title="Authored posts", participants=("self",), sender="self",
            occurred_at_utc=utc, occurred_at_local=utc.astimezone(tz),
            event_type="authored-content", content=content,
            attachments=tuple(attachments),
            references=tuple(dict.fromkeys([_reference("facebook", export_root, path), *[a.reference for a in attachments]])),
            raw_timestamp=str(stamp if stamp is not None else raw.get("timestamp")),
            source_reference=_reference("facebook", export_root, path),
        ))
    return events
