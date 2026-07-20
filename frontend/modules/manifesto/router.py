"""Routes for the Manifesto module."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from modules.manifesto.service import load_manifesto
from web import page_context, require_user, templates


router = APIRouter()


@router.get("/manifesto", response_class=HTMLResponse)
async def manifesto(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request,
        "modules/manifesto/index.html",
        page_context(
            request,
            user,
            "manifesto",
            manifesto=load_manifesto(),
        ),
    )
