"""Routes for the Home module."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from modules.registry import MODULES, module_by_key
from web import page_context, require_user, templates


router = APIRouter()


@router.get('/distill', response_class=HTMLResponse)
async def distill(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    # Temporarily retire the landing page while keeping existing bookmarks useful.
    return RedirectResponse('/hfl-corpus', status_code=307)


@router.get("/home", response_class=HTMLResponse)
async def home(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request,
        "modules/home/index.html",
        page_context(
            request,
            user,
            "home",
            module_cards=[
                module
                for module in MODULES
                if module.key not in {"home", "manifesto"}
            ],
            manifesto_module=module_by_key("manifesto"),
        ),
    )
