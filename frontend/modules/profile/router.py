"""Authenticated routes for the global owner profile."""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from modules.hfl_corpus.secrets import (
    clear_unlocked_cookie,
    normalize_secret_tags,
    update_profile_pin,
)
from modules.hfl_shares.security import make_csrf_token, verify_csrf_token, verify_pin
from modules.profile.service import apply_avatar, profile_from_form, stamp
from modules.profile.store import get_profile_store
from web import page_context, require_user, templates


router = APIRouter(prefix="/profile")


def _context(
    request: Request,
    user: str,
    *,
    profile=None,
    errors=None,
    saved=False,
    remove_avatar=False,
):
    return page_context(
        request,
        user,
        "profile",
        profile=profile or get_profile_store().get(),
        errors=errors or {},
        saved=saved,
        remove_avatar=remove_avatar,
        csrf=make_csrf_token(user),
    )


@router.get("", response_class=HTMLResponse)
async def profile_page(request: Request, saved: bool = False):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request,
        "modules/profile/index.html",
        _context(request, user, saved=saved),
    )


@router.post("", response_class=HTMLResponse)
async def save_profile(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    form = await request.form(max_files=1, max_fields=32)
    if not verify_csrf_token(str(form.get("csrf") or ""), user):
        raise HTTPException(status_code=403, detail="Invalid form token.")
    store = get_profile_store()
    saved_profile = store.get()
    draft, errors = profile_from_form(form, saved_profile)
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
    remove_avatar = str(form.get("remove_avatar") or "") == "on"
    draft, avatar_error = await apply_avatar(
        draft,
        form.get("avatar"),
        remove=remove_avatar,
    )
    if avatar_error:
        errors["avatar"] = avatar_error
    if errors:
        return templates.TemplateResponse(
            request,
            "modules/profile/index.html",
            _context(
                request,
                user,
                profile=draft,
                errors=errors,
                remove_avatar=remove_avatar,
            ),
            status_code=422,
        )
    store.save(stamp(draft))
    response = RedirectResponse("/profile?saved=true", status_code=303)
    if pin_change:
        clear_unlocked_cookie(response)
    return response
