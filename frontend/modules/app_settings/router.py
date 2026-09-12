"""Authenticated app settings."""
import os
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from modules.app_settings.store import read_settings, save_settings
from modules.hfl_shares.security import make_csrf_token, verify_csrf_token
from web import page_context, require_user, templates

router = APIRouter(prefix='/settings')


@router.get('', response_class=HTMLResponse)
async def settings_page(request: Request, saved: bool = False):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, 'modules/app_settings/index.html', page_context(
        request, user, 'settings', values=read_settings(), csrf=make_csrf_token(user), saved=saved,
        worker_configured=bool(os.getenv('HFL_AGENT_BRIDGE_TOKEN', '').strip())))


@router.post('')
async def update_settings(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    form = await request.form(max_files=0, max_fields=8)
    if not verify_csrf_token(str(form.get('csrf', '')), user):
        raise HTTPException(403, 'Invalid form token.')
    try:
        save_settings(form)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from None
    return RedirectResponse('/settings?saved=true', status_code=303)
