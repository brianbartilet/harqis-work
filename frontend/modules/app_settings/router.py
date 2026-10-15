"""Authenticated app settings."""
import os
from dataclasses import replace
from modules.profile.store import get_profile_store
from modules.profile.service import stamp
from modules.profile.corpus_settings import normalize_favorite_tags, corpus_secrets_from_form
from modules.hfl_corpus.secrets import clear_unlocked_cookie
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from modules.app_settings.store import read_settings, save_settings, validate_settings
from modules.hfl_shares.security import make_csrf_token, verify_csrf_token
from web import page_context, require_user, templates

router = APIRouter(prefix='/settings')


@router.get('', response_class=HTMLResponse)
async def settings_page(request: Request, saved: bool = False):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, 'modules/app_settings/index.html', page_context(
        request, user, 'settings', values=read_settings(), profile=get_profile_store().get(), errors={}, csrf=make_csrf_token(user), saved=saved,
        worker_configured=bool(os.getenv('HFL_AGENT_BRIDGE_TOKEN', '').strip())))


@router.post('')
@router.post('/corpus', response_class=HTMLResponse)
async def update_settings(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    form = await request.form(max_files=0, max_fields=40)
    if not verify_csrf_token(str(form.get('csrf', '')), user):
        raise HTTPException(403, 'Invalid form token.')
    open_sections = ",".join(section for section in ("agents", "activity-corpus")
                             if section in str(form.get("open_sections", "")).split(","))
    store = get_profile_store()
    saved = store.get()
    errors = {}
    values = read_settings()
    try:
        values = validate_settings(form, values)
    except (ValueError, TypeError) as exc:
        errors['settings'] = str(exc)
        values = {key: form.get(key, value) for key, value in values.items()}
    favorites = str(form.get('favorite_tags', saved.favorite_tags)).strip()
    tags = str(form.get('secret_tags', saved.secret_tags)).strip()
    try:
        favorites = normalize_favorite_tags(favorites)
    except ValueError as exc:
        errors['favorite_tags'] = str(exc)
    if len(tags) > 1000:
        errors['secret_tags'] = 'Use 1000 characters or fewer.'
    draft = replace(saved, favorite_tags=favorites, secret_tags=tags)
    draft, errors, pin_change = corpus_secrets_from_form(form, saved, draft, errors)
    if errors:
        return templates.TemplateResponse(request, 'modules/app_settings/index.html', page_context(
            request, user, 'settings', values=values, profile=draft, errors=errors, open_sections=open_sections,
            csrf=make_csrf_token(user), saved=False,
            worker_configured=bool(os.getenv('HFL_AGENT_BRIDGE_TOKEN', '').strip())), status_code=422)
    save_settings(values)
    store.save(stamp(draft))
    destination = '/settings?saved=true'
    if open_sections:
        destination += '&open=' + open_sections
    response = RedirectResponse(destination, status_code=303)
    if pin_change:
        clear_unlocked_cookie(response)
    return response
