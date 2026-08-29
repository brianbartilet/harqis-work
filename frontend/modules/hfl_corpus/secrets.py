"""Owner-session privacy controls for secret-tagged Activity Corpus entries."""

from __future__ import annotations

import hashlib
import hmac
import threading
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from fastapi import Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer

from config import get_settings
from modules.hfl_corpus.corpus import CorpusDocument, CorpusEntry
from modules.hfl_shares.security import hash_pin, verify_pin
from modules.profile.models import OwnerProfile


SECRET_COOKIE = "hfl_secrets_unlocked"
MANDATORY_SECRET_TAG = "secrets"
_PIN_WINDOW = timedelta(minutes=15)
_PIN_MAX_FAILURES = 5
_lock = threading.Lock()
_failures: dict[str, list[datetime]] = defaultdict(list)


def normalize_secret_tags(value: str) -> tuple[str, ...]:
    tags = [MANDATORY_SECRET_TAG]
    tags.extend(
        item.strip().lstrip("#").casefold()
        for item in (value or "").replace("\n", ",").split(",")
        if item.strip().lstrip("#")
    )
    return tuple(dict.fromkeys(tags))


def is_secret_entry(entry: CorpusEntry, tags: tuple[str, ...]) -> bool:
    protected = set(tags)
    return entry.secret or any(tag.casefold() in protected for tag in entry.tags)


def document_has_secrets(document: CorpusDocument, tags: tuple[str, ...]) -> bool:
    return any(is_secret_entry(entry, tags) for entry in document.entries)


def filter_document(document: CorpusDocument, tags: tuple[str, ...]) -> CorpusDocument:
    if not document_has_secrets(document, tags):
        return document
    entries = tuple(entry for entry in document.entries if not is_secret_entry(entry, tags))
    visible_tags = tuple(sorted({tag for entry in entries for tag in entry.tags}))
    counts = {tag: sum(tag in entry.tags for entry in entries) for tag in visible_tags}
    visible_text = "\n\n".join(f"## {entry.text}" for entry in entries)
    return replace(
        document,
        text=visible_text,
        tags=visible_tags,
        references=(),
        excerpt=" ".join(visible_text.split())[:240],
        tag_counts=tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:10]),
        entry_count=len(entries),
        entries=entries,
        tag_entry_anchors=tuple(
            (tag, entry.anchor) for entry in entries for tag in entry.tags
        ),
    )


def filter_documents(
    documents: tuple[CorpusDocument, ...], tags: tuple[str, ...]
) -> tuple[CorpusDocument, ...]:
    filtered = tuple(filter_document(document, tags) for document in documents)
    return tuple(
        visible
        for original, visible in zip(documents, filtered)
        if visible.entries or not original.entry_count
    )


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="hfl-secret-owner-session")


def _pin_fingerprint(profile: OwnerProfile) -> str:
    return hashlib.sha256(profile.secret_pin_hash.encode("utf-8")).hexdigest()


def secrets_unlocked(request: Request, profile: OwnerProfile) -> bool:
    if not profile.secret_pin_hash:
        return False
    try:
        payload = _serializer().loads(
            request.cookies.get(SECRET_COOKIE, ""),
            max_age=get_settings().session_max_age,
        )
        return hmac.compare_digest(str(payload.get("pin") or ""), _pin_fingerprint(profile))
    except (BadSignature, TypeError):
        return False


def set_unlocked_cookie(response: Response, profile: OwnerProfile) -> None:
    response.set_cookie(
        SECRET_COOKIE,
        _serializer().dumps({"pin": _pin_fingerprint(profile)}),
        max_age=get_settings().session_max_age,
        httponly=True,
        secure=get_settings().behind_proxy,
        samesite="strict",
        path="/",
    )


def clear_unlocked_cookie(response: Response) -> None:
    response.delete_cookie(SECRET_COOKIE, path="/")


def _failure_key(request: Request, user: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{user}:{host}"


def pin_rate_limited(request: Request, user: str) -> bool:
    key = _failure_key(request, user)
    cutoff = datetime.now(timezone.utc) - _PIN_WINDOW
    with _lock:
        _failures[key] = [stamp for stamp in _failures[key] if stamp > cutoff]
        return len(_failures[key]) >= _PIN_MAX_FAILURES


def verify_owner_pin(request: Request, user: str, pin: str, profile: OwnerProfile) -> bool:
    key = _failure_key(request, user)
    if pin_rate_limited(request, user):
        return False
    valid = bool(pin.isdigit() and len(pin) == 6 and verify_pin(pin, profile.secret_pin_hash))
    with _lock:
        if valid:
            _failures.pop(key, None)
        else:
            _failures[key].append(datetime.now(timezone.utc))
    return valid


def update_profile_pin(profile: OwnerProfile, new_pin: str) -> OwnerProfile:
    return replace(profile, secret_pin_hash=hash_pin(new_pin) if new_pin else "")
