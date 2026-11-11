"""Authenticated HUD; layout writes use the shared owner CSRF contract."""
import asyncio
import hashlib
from pathlib import Path

from fastapi import APIRouter, Request
from modules.hfl_corpus.router import _workspace_authorize
from modules.hfl_shares.security import make_csrf_token
from modules.second_brain import hud, agent_hud
from web import page_context, require_user, templates

router = APIRouter()


@router.get('/second-brain')
async def page(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, 'modules/second_brain/hud.html', page_context(
        request, user, 'second_brain', hud_catalog=hud.inventory(), hud_sizes=hud.SIZES,
        hud_csrf=make_csrf_token(user), hud_colors=hud.PIN_COLORS))


@router.get('/second-brain/hud/data')
async def data(request: Request):
    _workspace_authorize(request)
    return await asyncio.to_thread(hud.data)


@router.get('/second-brain/hud/layout')
async def read_layout(request: Request):
    _workspace_authorize(request)
    return await asyncio.to_thread(hud.layout)


@router.put('/second-brain/hud/layout')
async def save(request: Request, payload: hud.Layout):
    _workspace_authorize(request, write=True)
    return await asyncio.to_thread(hud.save_layout, payload)


@router.get('/second-brain/hud/build-context')
async def build_context(request: Request):
    _workspace_authorize(request)
    path = Path(__file__).resolve().parents[3]
    skills = ['create-new-hud', 'create-new-service-app', 'create-new-workflow']
    return {'instructions': (path / 'workflows/second_brain/prompts/build_widget.md').read_text(encoding='utf-8'),
            'skills': [{'name': name, 'sha256': hashlib.sha256((path / '.agents/skills' / name / 'SKILL.md').read_bytes()).hexdigest()} for name in skills]}


@router.get('/agents/hud/data')
async def agent_data(request: Request):
    _workspace_authorize(request)
    return await asyncio.to_thread(agent_hud.data)


@router.get('/agents/hud/layout')
async def agent_layout(request: Request):
    _workspace_authorize(request)
    return await asyncio.to_thread(agent_hud.layout)


@router.put('/agents/hud/layout')
async def save_agent_layout(request: Request, payload: agent_hud.Layout):
    _workspace_authorize(request, write=True)
    return await asyncio.to_thread(agent_hud.save_layout, payload)
