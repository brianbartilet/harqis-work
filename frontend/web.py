"""Shared template and authentication helpers for frontend modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from auth import get_current_user
from config import get_settings
from modules.registry import MODULES


FRONTEND_ROOT = Path(__file__).resolve().parent
REPO_ROOT = FRONTEND_ROOT.parent
templates = Jinja2Templates(directory=str(FRONTEND_ROOT / "templates"))


def require_user(request: Request) -> tuple[str | None, RedirectResponse | None]:
    user = get_current_user(request)
    if user:
        return user, None
    return None, RedirectResponse("/login", status_code=302)


def page_context(
    request: Request,
    user: str,
    active_module: str,
    **values: Any,
) -> dict[str, Any]:
    return {
        "request": request,
        "user": user,
        "active_module": active_module,
        "modules": MODULES,
        "flower_url": get_settings().flower_url,
        **values,
    }
