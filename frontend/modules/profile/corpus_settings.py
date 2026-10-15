"""Validation shared by owner corpus settings and legacy profile submissions."""
from dataclasses import replace
import re
from modules.hfl_corpus.secrets import normalize_secret_tags, update_profile_pin
from modules.hfl_shares.security import verify_pin


def normalize_favorite_tags(value):
    if len(value) > 1000:
        raise ValueError("Use 1000 characters or fewer.")
    tags = []
    seen = set()
    for item in value.split(','):
        tag = item.strip().lstrip('#')
        if not tag:
            continue
        if not re.fullmatch(r"[\w-]+", tag):
            raise ValueError("Separate tags with commas; use letters, numbers, underscores or hyphens.")
        if tag.casefold() not in seen:
            tags.append('#' + tag)
            seen.add(tag.casefold())
    return ', '.join(tags)


def corpus_secrets_from_form(form, saved_profile, draft, errors):
    current_pin = str(form.get("current_secret_pin") or "").strip()
    new_pin = str(form.get("new_secret_pin") or "").strip()
    confirm_pin = str(form.get("confirm_secret_pin") or "").strip()
    remove_pin = str(form.get("remove_secret_pin") or "") == "on"
    pin_change = bool(new_pin or remove_pin)
    if pin_change and saved_profile.secret_pin_hash and not verify_pin(
        current_pin, saved_profile.secret_pin_hash
    ):
        errors["current_secret_pin"] = "Enter the current PIN."
    if new_pin and (len(new_pin) != 6 or not new_pin.isdigit()):
        errors["new_secret_pin"] = "Use exactly six digits."
    if new_pin and new_pin != confirm_pin:
        errors["confirm_secret_pin"] = "PINs do not match."
    normalized_tags = normalize_secret_tags(draft.secret_tags)
    draft = replace(
        draft,
        secret_tags=", ".join(f"#{tag}" for tag in normalized_tags),
    )
    pin_error_fields = (
        "current_secret_pin",
        "new_secret_pin",
        "confirm_secret_pin",
    )
    if pin_change and not any(key in errors for key in pin_error_fields):
        draft = update_profile_pin(draft, "" if remove_pin else new_pin)
    return draft, errors, pin_change
