"""Validation and avatar processing for owner profile updates."""

from __future__ import annotations

import io
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from PIL import Image, ImageOps, UnidentifiedImageError

from modules.profile.models import OwnerProfile


_LIMITS = {
    "first_name": 80,
    "last_name": 80,
    "nickname": 50,
    "location": 120,
    "phone": 32,
    "bio": 500,
    "email": 254,
    "linkedin_url": 500,
    "github_url": 500,
    "website_url": 500,
    "instagram_url": 500,
}
_PHONE = re.compile(r"^\+[1-9][0-9 ()-]{6,30}$")
_EMAIL = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)
_ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
_MAX_AVATAR_BYTES = 2 * 1024 * 1024


def _clean(form: Any, field: str) -> str:
    return str(form.get(field) or "").strip()


def _valid_email(value: str) -> bool:
    return bool(_EMAIL.fullmatch(value) and len(value.rsplit("@", 1)[0]) <= 64)


def _valid_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(
        parsed.scheme == "https"
        and parsed.netloc
        and not parsed.username
        and not parsed.password
        and not any(char.isspace() or ord(char) < 32 for char in value)
    )


def profile_from_form(form: Any, saved: OwnerProfile) -> tuple[OwnerProfile, dict[str, str]]:
    values = {field: _clean(form, field) for field in _LIMITS}
    errors: dict[str, str] = {}
    for field, limit in _LIMITS.items():
        if len(values[field]) > limit:
            errors[field] = f"Use {limit} characters or fewer."
    if values["email"] and not _valid_email(values["email"]):
        errors["email"] = "Enter a valid email address."
    phone_digits = sum(char.isdigit() for char in values["phone"])
    if values["phone"] and (
        not _PHONE.fullmatch(values["phone"])
        or not 8 <= phone_digits <= 15
    ):
        errors["phone"] = "Enter a complete international number beginning with +."
    for field in ("linkedin_url", "github_url", "website_url", "instagram_url"):
        if values[field] and not _valid_https_url(values[field]):
            errors[field] = "Enter a complete HTTPS URL."
    secret_tags = _clean(form, "secret_tags")
    if len(secret_tags) > 1000:
        errors["secret_tags"] = "Use 1000 characters or fewer."
    profile = OwnerProfile(
        **values,
        secret_pin_hash=saved.secret_pin_hash,
        secret_tags=secret_tags,
    ).with_avatar_from(saved)
    return profile, errors


async def apply_avatar(
    profile: OwnerProfile,
    upload: Any,
    *,
    remove: bool,
) -> tuple[OwnerProfile, str]:
    if remove:
        return replace(profile, avatar=b"", avatar_content_type=""), ""
    if not upload or not getattr(upload, "filename", ""):
        return profile, ""
    raw = await upload.read(_MAX_AVATAR_BYTES + 1)
    if len(raw) > _MAX_AVATAR_BYTES:
        return profile, "Choose an image no larger than 2 MB."
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in _ALLOWED_IMAGE_FORMATS:
                raise ValueError("unsupported")
            source.verify()
        with Image.open(io.BytesIO(raw)) as source:
            if source.width * source.height > 25_000_000:
                raise ValueError("image dimensions too large")
            normalized = ImageOps.exif_transpose(source).convert("RGB")
            thumbnail = ImageOps.fit(
                normalized,
                (256, 256),
                method=Image.Resampling.LANCZOS,
            )
            output = io.BytesIO()
            thumbnail.save(output, format="WEBP", quality=86, method=6)
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
        return profile, "Choose a valid JPEG, PNG, or WebP image."
    return replace(
        profile,
        avatar=output.getvalue(),
        avatar_content_type="image/webp",
    ), ""


def stamp(profile: OwnerProfile) -> OwnerProfile:
    return replace(profile, updated_at=datetime.now(timezone.utc).isoformat())
