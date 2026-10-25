"""Shared template and authentication helpers for frontend modules."""

from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from auth import get_current_user
from config import get_settings
from modules.registry import PRIMARY_MODULES
from modules.profile.store import get_profile_store


FRONTEND_ROOT = Path(__file__).resolve().parent
REPO_ROOT = FRONTEND_ROOT.parent
STATIC_ROOT = FRONTEND_ROOT / "static"
templates = Jinja2Templates(directory=str(FRONTEND_ROOT / "templates"))


@lru_cache(maxsize=256)
def _asset_digest(asset_path: Path, modified_ns: int, size: int) -> str:
    """Cache unchanged files while invalidating URLs after local edits."""
    return hashlib.sha256(asset_path.read_bytes()).hexdigest()[:12]


def static_asset(relative_path: str) -> str:
    """Return a same-origin static URL versioned by its content digest."""
    asset_path = (STATIC_ROOT / relative_path).resolve()
    try:
        asset_path.relative_to(STATIC_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("static asset must remain under frontend/static") from exc
    stat = asset_path.stat()
    digest = _asset_digest(asset_path, stat.st_mtime_ns, stat.st_size)
    return f"/static/{relative_path}?v={digest}"


templates.env.globals["static_asset"] = static_asset

SHARE_ASSETS = frozenset({
    'favicon.svg', 'css/share-activity.css', 'css/share-guest.css',
    'js/share-graphs.js', 'js/share-activity.js',
    'js/share-graphs.js.LEGAL.txt', 'js/share-graphs.LICENSES.txt',
})


def share_asset(relative_path: str) -> str:
    """Keep recipient assets inside the publicly routed /share namespace."""
    if relative_path not in SHARE_ASSETS:
        raise ValueError('Not a public share asset')
    return static_asset(relative_path).replace('/static/', '/share/assets/', 1)


templates.env.globals['share_asset'] = share_asset


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
    from modules.hfl_shares.security import make_csrf_token
    return {
        "butler_csrf": make_csrf_token(user),
        "request": request,
        "corpus_entities_enabled": bool(os.environ.get('HARQIS_ENTITIES_DB')),
        "user": user,
        "active_module": active_module,
        "modules": PRIMARY_MODULES,
        "flower_url": get_settings().flower_url,
        "owner_profile": get_profile_store().get(),
        **values,
    }
